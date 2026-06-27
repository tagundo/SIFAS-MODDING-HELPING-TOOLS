# texture_importer.py
# UnityPy Texture Importer (Single / Single-Image / Batch)
#
# Features:
#   * Visual preview of the texture currently inside the bundle AND the
#     replacement image, side by side.
#   * Import a whole folder (matched by texture name) OR a single image file
#     into one selected texture.
#   * Detailed error reporting: a Log panel plus full tracebacks and a
#     per-texture failure breakdown.
#   * English UI by default with a Korean (한국어) language switch.
#   * Save the output bundle next to the input bundle with a suffix that
#     marks it as "texture inserted" (default: "_textured").
#
# Requirements: pip install UnityPy Pillow
import os
import sys
import traceback
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

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


def _ensure_deps():
    """Make sure UnityPy and Pillow are importable; install if missing.

    The order matters: we check both before importing so a missing Pillow
    does not crash the script before the installer runs.
    """
    missing = []
    try:
        import UnityPy  # noqa: F401
    except ImportError:
        missing.append("UnityPy")
    try:
        import PIL  # noqa: F401
    except ImportError:
        missing.append("Pillow")
    if missing:
        import subprocess
        print("Installing missing dependencies: " + ", ".join(missing))
        subprocess.check_call([sys.executable, "-m", "pip", "install"] + missing)


_ensure_deps()

import UnityPy
from UnityPy.enums import TextureFormat
from PIL import Image, ImageTk, ImageDraw

SUPPORTED_IMG_EXTS = [".png", ".jpg", ".jpeg", ".bmp", ".tga"]
# SIFAS bundles use the ".unity" extension, so it leads the list. The rest are
# kept for compatibility with other Unity asset-bundle naming conventions, and
# "" matches extension-less bundles.
SUPPORTED_BUNDLE_EXTS = [".unity", ".bundle", ".unity3d", ".ab", ".assets", ""]
DEFAULT_SUFFIX = "_textured"
PREVIEW_W, PREVIEW_H = 260, 280

TEXTURE_FORMATS = [
    "Keep Original",
    "RGB24", "RGBA32", "ARGB32", "RGB565", "RGBA4444", "Alpha8",
    "DXT1", "DXT5",
    "BC4", "BC5", "BC6H", "BC7",
    "ETC_RGB4", "ETC2_RGB", "ETC2_RGBA1", "ETC2_RGBA8",
    "EAC_R", "EAC_RG",
    "ASTC_4x4", "ASTC_5x5", "ASTC_6x6", "ASTC_8x8", "ASTC_10x10", "ASTC_12x12",
    "RHalf", "RGHalf", "RGBAHalf",
    "RFloat", "RGFloat", "RGBAFloat",
]


# ============================================================================
# Translations (i18n). English is the default; Korean is selectable.
# Keys are shared; values use str.format(...) named placeholders where needed.
# ============================================================================
STRINGS = {
    "en": {
        "title": "UnityPy Texture Importer",
        "language_label": "Language:",
        "format_label": "Texture Format:",
        "tab_single": "Single Bundle",
        "tab_batch": "Batch",

        "bundle_file": "Bundle File:",
        "browse": "Browse",
        "load_textures": "Load / Preview Textures",

        "image_source": "Image Source",
        "src_folder": "Image folder (match by texture name)",
        "src_single": "Single image file (replace the selected texture)",
        "image_folder": "Image Folder:",
        "single_image_file": "Image File:",

        "output": "Output",
        "out_same": "Save next to input bundle (with suffix)",
        "out_custom": "Custom output path",
        "suffix_label": "Suffix:",
        "output_bundle": "Output Bundle:",

        "textures": "Textures in Bundle",
        "current_texture": "Current Texture (in bundle)",
        "replacement_image": "Replacement Image",
        "no_image": "No image",
        "no_match": "No matching image found",
        "decode_failed": "Decode failed:\n{err}",
        "import_single": "Import",

        "bundle_selection": "Bundle Selection",
        "add_files": "Add Bundle Files",
        "add_folder": "Add Folder",
        "clear_all": "Clear All",
        "recursive": "Recursive folder scan",
        "image_root": "Image Root:",
        "output_folder": "Output Folder:",
        "out_same_each": "Save next to each input bundle (with suffix)",
        "out_to_folder": "Save into a single output folder",
        "preserve_tree": "Preserve input folder tree",
        "import_batch": "Import (Batch)",

        "log": "Log",
        "clear_log": "Clear Log",
        "status_ready": "Ready",
        "status_error": "Error - see Log for details",

        "err_title": "Error",
        "warn_title": "Warning",
        "done_title": "Done",
        "done_with_errors_title": "Done (with errors)",

        "err_select_bundle": "Please select a valid bundle file.",
        "err_select_image_folder": "Please select a valid image folder.",
        "err_select_image_file": "Please select a valid image file.",
        "err_select_output": "Please set the output bundle path.",
        "err_no_texture_selected": "Select a texture from the list first (load textures, then click one).",
        "err_overwrite_input": "The output path is the same as the input bundle.\nChange the suffix or the output path so the original is not overwritten.",
        "err_no_bundles": "No bundle files selected. Use 'Add Bundle Files' or 'Add Folder'.",
        "err_select_image_root": "Please select a valid image root folder.",
        "err_select_output_folder": "Please select an output folder.",
        "err_empty_suffix": "Suffix is empty; using default '{suffix}' so the input is not overwritten.",

        "importing_single": "Importing...",
        "importing_batch": "Importing (batch)...",
        "found_textures": "Found {count} texture(s). Click one to preview.",
        "no_textures_found": "No Texture2D objects found in this bundle.",
        "preview_failed": "Failed to read bundle:\n{err}",

        "done_single": "Imported {imported} texture(s), skipped {skipped}.\n\nSaved to:\n{path}",
        "done_single_errors": "Imported {imported}, skipped {skipped}, errors {errors}.\n\nSaved to:\n{path}\n\nFirst errors:",
        "done_single_status": "Done. Imported {n} texture(s).",
        "done_batch": "Bundles processed: {processed} (failed {failed}).\nImported textures: {imported}, skipped {skipped}.",
        "done_batch_errors": "Bundles processed: {processed} (failed {failed}).\nImported textures: {imported}, skipped {skipped}.\nErrors: {errors}\n\nFirst errors:",
        "done_batch_status": "Batch done. {imported} texture(s) over {processed} bundle(s).",
        "batch_progress": "[{i}/{total}] Saved {path} (imported {n})",
        "batch_failed_item": "Failed: {path} - see Log",
        "see_log": "See the Log panel for the full details / traceback.",
        "more_errors": "\n... and {n} more.",
        "fatal_error": "A fatal error occurred:\n{err}\n\nSee the Log panel for the full traceback.",

        "added_files": "Added {n} file(s). Total: {total}",
        "added_folder": "Added {n} bundle(s) from folder. Total: {total}",
        "cleared": "Bundle list cleared.",
    },
    "ko": {
        "title": "UnityPy 텍스처 임포터",
        "language_label": "언어:",
        "format_label": "텍스처 포맷:",
        "tab_single": "단일 번들",
        "tab_batch": "일괄 처리",

        "bundle_file": "번들 파일:",
        "browse": "찾아보기",
        "load_textures": "텍스처 불러오기 / 미리보기",

        "image_source": "이미지 소스",
        "src_folder": "이미지 폴더 (텍스처 이름으로 매칭)",
        "src_single": "단일 이미지 파일 (선택한 텍스처 교체)",
        "image_folder": "이미지 폴더:",
        "single_image_file": "이미지 파일:",

        "output": "출력",
        "out_same": "입력 번들과 같은 폴더에 저장 (접미사 추가)",
        "out_custom": "사용자 지정 경로",
        "suffix_label": "접미사:",
        "output_bundle": "출력 번들:",

        "textures": "번들 내 텍스처",
        "current_texture": "현재 텍스처 (번들 내부)",
        "replacement_image": "교체할 이미지",
        "no_image": "이미지 없음",
        "no_match": "일치하는 이미지를 찾을 수 없음",
        "decode_failed": "디코딩 실패:\n{err}",
        "import_single": "임포트",

        "bundle_selection": "번들 선택",
        "add_files": "번들 파일 추가",
        "add_folder": "폴더 추가",
        "clear_all": "전체 비우기",
        "recursive": "하위 폴더까지 검색",
        "image_root": "이미지 루트:",
        "output_folder": "출력 폴더:",
        "out_same_each": "각 입력 번들과 같은 폴더에 저장 (접미사 추가)",
        "out_to_folder": "하나의 출력 폴더에 저장",
        "preserve_tree": "입력 폴더 구조 유지",
        "import_batch": "임포트 (일괄)",

        "log": "로그",
        "clear_log": "로그 지우기",
        "status_ready": "준비됨",
        "status_error": "오류 - 자세한 내용은 로그를 확인하세요",

        "err_title": "오류",
        "warn_title": "경고",
        "done_title": "완료",
        "done_with_errors_title": "완료 (오류 있음)",

        "err_select_bundle": "올바른 번들 파일을 선택하세요.",
        "err_select_image_folder": "올바른 이미지 폴더를 선택하세요.",
        "err_select_image_file": "올바른 이미지 파일을 선택하세요.",
        "err_select_output": "출력 번들 경로를 지정하세요.",
        "err_no_texture_selected": "먼저 목록에서 텍스처를 선택하세요 (텍스처를 불러온 뒤 항목을 클릭).",
        "err_overwrite_input": "출력 경로가 입력 번들과 동일합니다.\n원본을 덮어쓰지 않도록 접미사나 출력 경로를 변경하세요.",
        "err_no_bundles": "선택된 번들 파일이 없습니다. '번들 파일 추가' 또는 '폴더 추가'를 사용하세요.",
        "err_select_image_root": "올바른 이미지 루트 폴더를 선택하세요.",
        "err_select_output_folder": "출력 폴더를 선택하세요.",
        "err_empty_suffix": "접미사가 비어 있어 기본값 '{suffix}'을(를) 사용합니다 (원본 보호).",

        "importing_single": "임포트 중...",
        "importing_batch": "일괄 임포트 중...",
        "found_textures": "텍스처 {count}개를 찾았습니다. 항목을 클릭하면 미리보기됩니다.",
        "no_textures_found": "이 번들에서 Texture2D 객체를 찾을 수 없습니다.",
        "preview_failed": "번들을 읽지 못했습니다:\n{err}",

        "done_single": "{imported}개 텍스처 임포트, {skipped}개 건너뜀.\n\n저장 위치:\n{path}",
        "done_single_errors": "{imported}개 임포트, {skipped}개 건너뜀, 오류 {errors}개.\n\n저장 위치:\n{path}\n\n주요 오류:",
        "done_single_status": "완료. {n}개 텍스처를 임포트했습니다.",
        "done_batch": "처리한 번들: {processed}개 (실패 {failed}개).\n임포트한 텍스처: {imported}개, 건너뜀: {skipped}개.",
        "done_batch_errors": "처리한 번들: {processed}개 (실패 {failed}개).\n임포트한 텍스처: {imported}개, 건너뜀: {skipped}개.\n오류: {errors}개\n\n주요 오류:",
        "done_batch_status": "일괄 완료. 번들 {processed}개에서 텍스처 {imported}개.",
        "batch_progress": "[{i}/{total}] 저장됨 {path} (임포트 {n})",
        "batch_failed_item": "실패: {path} - 로그 확인",
        "see_log": "전체 내용/트레이스백은 로그 패널을 확인하세요.",
        "more_errors": "\n... 외 {n}개 더.",
        "fatal_error": "치명적 오류가 발생했습니다:\n{err}\n\n전체 트레이스백은 로그 패널을 확인하세요.",

        "added_files": "{n}개 파일 추가됨. 총 {total}개",
        "added_folder": "폴더에서 번들 {n}개 추가됨. 총 {total}개",
        "cleared": "번들 목록을 비웠습니다.",
    },
    "ja": {
        "title": "UnityPy テクスチャインポーター",
        "language_label": "言語:",
        "format_label": "テクスチャ形式:",
        "tab_single": "単一バンドル",
        "tab_batch": "一括処理",

        "bundle_file": "バンドルファイル:",
        "browse": "参照",
        "load_textures": "テクスチャを読み込み / プレビュー",

        "image_source": "画像ソース",
        "src_folder": "画像フォルダ（テクスチャ名で照合）",
        "src_single": "単一画像ファイル（選択中のテクスチャを置換）",
        "image_folder": "画像フォルダ:",
        "single_image_file": "画像ファイル:",

        "output": "出力",
        "out_same": "入力バンドルと同じ場所に保存（接尾辞付き）",
        "out_custom": "出力パスを指定",
        "suffix_label": "接尾辞:",
        "output_bundle": "出力バンドル:",

        "textures": "バンドル内のテクスチャ",
        "current_texture": "現在のテクスチャ（バンドル内）",
        "replacement_image": "置換する画像",
        "no_image": "画像なし",
        "no_match": "一致する画像が見つかりません",
        "decode_failed": "デコードに失敗しました:\n{err}",
        "import_single": "インポート",

        "bundle_selection": "バンドル選択",
        "add_files": "バンドルファイルを追加",
        "add_folder": "フォルダを追加",
        "clear_all": "すべてクリア",
        "recursive": "サブフォルダも検索",
        "image_root": "画像ルート:",
        "output_folder": "出力フォルダ:",
        "out_same_each": "各入力バンドルと同じ場所に保存（接尾辞付き）",
        "out_to_folder": "1つの出力フォルダに保存",
        "preserve_tree": "入力フォルダ構造を維持",
        "import_batch": "インポート（一括）",

        "log": "ログ",
        "clear_log": "ログをクリア",
        "status_ready": "準備完了",
        "status_error": "エラー - 詳細はログを確認してください",

        "err_title": "エラー",
        "warn_title": "警告",
        "done_title": "完了",
        "done_with_errors_title": "完了（エラーあり）",

        "err_select_bundle": "有効なバンドルファイルを選択してください。",
        "err_select_image_folder": "有効な画像フォルダを選択してください。",
        "err_select_image_file": "有効な画像ファイルを選択してください。",
        "err_select_output": "出力バンドルのパスを指定してください。",
        "err_no_texture_selected": "先にリストからテクスチャを選択してください（読み込んでから項目をクリック）。",
        "err_overwrite_input": "出力パスが入力バンドルと同じです。\n原本を上書きしないよう、接尾辞か出力パスを変更してください。",
        "err_no_bundles": "バンドルファイルが選択されていません。「バンドルファイルを追加」か「フォルダを追加」を使ってください。",
        "err_select_image_root": "有効な画像ルートフォルダを選択してください。",
        "err_select_output_folder": "出力フォルダを選択してください。",
        "err_empty_suffix": "接尾辞が空のため、原本を上書きしないよう既定値 '{suffix}' を使用します。",

        "importing_single": "インポート中...",
        "importing_batch": "一括インポート中...",
        "found_textures": "テクスチャを {count} 個見つけました。クリックでプレビューします。",
        "no_textures_found": "このバンドルにTexture2Dオブジェクトが見つかりません。",
        "preview_failed": "バンドルの読み込みに失敗しました:\n{err}",

        "done_single": "{imported} 個のテクスチャをインポート、{skipped} 個をスキップ。\n\n保存先:\n{path}",
        "done_single_errors": "{imported} 個インポート、{skipped} 個スキップ、エラー {errors} 件。\n\n保存先:\n{path}\n\n主なエラー:",
        "done_single_status": "完了。{n} 個のテクスチャをインポートしました。",
        "done_batch": "処理したバンドル: {processed} 個（失敗 {failed} 個）。\nインポートしたテクスチャ: {imported} 個、スキップ: {skipped} 個。",
        "done_batch_errors": "処理したバンドル: {processed} 個（失敗 {failed} 個）。\nインポートしたテクスチャ: {imported} 個、スキップ: {skipped} 個。\nエラー: {errors} 件\n\n主なエラー:",
        "done_batch_status": "一括完了。{processed} 個のバンドルで {imported} 個のテクスチャ。",
        "batch_progress": "[{i}/{total}] 保存しました {path}（インポート {n}）",
        "batch_failed_item": "失敗: {path} - ログを確認",
        "see_log": "詳細やトレースバックはログパネルを確認してください。",
        "more_errors": "\n... 他 {n} 件。",
        "fatal_error": "致命的なエラーが発生しました:\n{err}\n\n完全なトレースバックはログパネルを確認してください。",

        "added_files": "{n} 個のファイルを追加。合計: {total} 個",
        "added_folder": "フォルダからバンドルを {n} 個追加。合計: {total} 個",
        "cleared": "バンドルリストをクリアしました。",
    },
}


# ============================================================================
# Helpers (pure / non-UI)
# ============================================================================
def find_image_by_name(img_root, name):
    if not img_root or not name:
        return None
    for ext in SUPPORTED_IMG_EXTS:
        p = os.path.join(img_root, name + ext)
        if os.path.exists(p):
            return p
    return None


def safe_make_dir(p):
    d = os.path.dirname(p)
    if d:
        os.makedirs(d, exist_ok=True)


def open_image_checked(path):
    """Open an image and force-load it so errors surface here, not later."""
    img = Image.open(path)
    img.load()
    return img


def iter_bundle_files(input_root, recursive):
    if os.path.isfile(input_root):
        yield input_root
        return
    if recursive:
        for root, _, files in os.walk(input_root):
            for fn in files:
                ext = os.path.splitext(fn)[1].lower()
                if ext in SUPPORTED_BUNDLE_EXTS:
                    yield os.path.join(root, fn)
    else:
        for fn in os.listdir(input_root):
            fp = os.path.join(input_root, fn)
            if os.path.isfile(fp):
                ext = os.path.splitext(fn)[1].lower()
                if ext in SUPPORTED_BUNDLE_EXTS:
                    yield fp


def process_bundle(bundle_path, out_path, resolver, fmt_name, log):
    """Replace textures in a bundle and save it.

    resolver(texture_name) -> image path to use, or None to skip.
    log(str) is called with progress / error lines.

    Returns (imported, skipped, errors) where errors is a list of tuples:
        (texture_name, image_path_or_None, message, traceback_str)
    """
    log("Loading bundle: {}".format(bundle_path))
    env = UnityPy.load(bundle_path)
    imported = 0
    skipped = 0
    errors = []
    found_tex = 0

    for obj in env.objects:
        if obj.type.name != "Texture2D":
            continue
        found_tex += 1
        try:
            data = obj.read()
        except Exception as e:
            tb = traceback.format_exc()
            errors.append(("<unreadable Texture2D>", None, str(e), tb))
            log("  ! ERROR reading a Texture2D: {}".format(e))
            continue

        name = getattr(data, "m_Name", "") or ""
        img_path = resolver(name)
        if not img_path:
            skipped += 1
            log("  - skip (no image): {}".format(name))
            continue

        try:
            pil = open_image_checked(img_path)
            if fmt_name and fmt_name != "Keep Original":
                fmt = getattr(TextureFormat, fmt_name, None)
                if fmt is not None:
                    data.m_TextureFormat = fmt
            data.image = pil
            data.save()
            imported += 1
            log("  + {}  <=  {}".format(name, os.path.basename(img_path)))
        except Exception as e:
            tb = traceback.format_exc()
            errors.append((name, img_path, str(e), tb))
            log("  ! ERROR on '{}': {}".format(name, e))

    if found_tex == 0:
        log("  (no Texture2D objects in this bundle)")

    # Save the (possibly modified) bundle.
    safe_make_dir(out_path)
    with open(out_path, "wb") as f:
        f.write(env.file.save(packer="lz4"))
    log("Saved: {}  (imported {}, skipped {}, errors {})".format(
        out_path, imported, skipped, len(errors)))

    return imported, skipped, errors


# ============================================================================
# GUI
# ============================================================================
class App:
    def __init__(self, root):
        self.root = root
        # Default to the shared/persisted language when available (English otherwise).
        default_lang = "en"
        if _shared_i18n is not None:
            cand = _shared_i18n.get_language()
            if cand in STRINGS:
                default_lang = cand
        self.lang = tk.StringVar(value=default_lang)
        self._retranslate = []   # list of zero-arg callables that re-apply text

        # ---- shared state ----
        self.texture_format = tk.StringVar(value="Keep Original")

        # Single tab
        self.single_bundle = tk.StringVar()
        self.single_src_mode = tk.StringVar(value="folder")   # "folder" | "single"
        self.single_images = tk.StringVar()
        self.single_image_file = tk.StringVar()
        self.single_out_mode = tk.StringVar(value="same")     # "same" | "custom"
        self.single_suffix = tk.StringVar(value=DEFAULT_SUFFIX)
        self.single_output = tk.StringVar()
        self.single_tex_data = []   # cached read Texture2D objects (aligned to listbox)

        # Batch tab
        self.batch_bundles = []
        self.batch_images = tk.StringVar()
        self.batch_out_mode = tk.StringVar(value="same")      # "same" | "folder"
        self.batch_output = tk.StringVar()
        self.batch_recursive = tk.BooleanVar(value=True)
        self.batch_preserve_tree = tk.BooleanVar(value=False)
        self.batch_suffix = tk.StringVar(value=DEFAULT_SUFFIX)

        self.root.geometry("1100x880")
        self.root.minsize(940, 760)
        self._build_ui()

        # Recompute single output whenever its inputs change.
        self.single_bundle.trace_add("write", lambda *a: self._single_recompute_output())
        self.single_suffix.trace_add("write", lambda *a: self._single_recompute_output())
        self._single_on_srcmode()
        self._single_on_outmode()
        self._batch_on_outmode()
        self._retranslate_all()

    # ---- translation ----
    def t(self, key, **kw):
        table = STRINGS.get(self.lang.get(), STRINGS["en"])
        s = table.get(key, STRINGS["en"].get(key, key))
        return s.format(**kw) if kw else s

    def _register(self, setter):
        self._retranslate.append(setter)

    def _retranslate_all(self):
        for fn in self._retranslate:
            try:
                fn()
            except Exception:
                pass

    def _change_language(self, code):
        self.lang.set(code)
        # Remember the choice for the other tools too (best-effort).
        if _shared_i18n is not None:
            try:
                _shared_i18n.set_language(code)
            except Exception:  # noqa: BLE001
                pass
        self._retranslate_all()

    # ---- translatable widget factories ----
    def _mk_label(self, parent, key, **kw):
        w = ttk.Label(parent, text=self.t(key), **kw)
        self._register(lambda w=w, k=key: w.config(text=self.t(k)))
        return w

    def _mk_button(self, parent, key, command, **kw):
        w = ttk.Button(parent, text=self.t(key), command=command, **kw)
        self._register(lambda w=w, k=key: w.config(text=self.t(k)))
        return w

    def _mk_check(self, parent, key, variable, **kw):
        w = ttk.Checkbutton(parent, text=self.t(key), variable=variable, **kw)
        self._register(lambda w=w, k=key: w.config(text=self.t(k)))
        return w

    def _mk_radio(self, parent, key, variable, value, command=None, **kw):
        w = ttk.Radiobutton(parent, text=self.t(key), variable=variable,
                            value=value, command=command, **kw)
        self._register(lambda w=w, k=key: w.config(text=self.t(k)))
        return w

    def _mk_labelframe(self, parent, key, **kw):
        w = ttk.LabelFrame(parent, text=self.t(key), **kw)
        self._register(lambda w=w, k=key: w.config(text=self.t(k)))
        return w

    def _file_row(self, parent, label_key, var, browse_fn):
        """Label + Entry + Browse. Returns (entry, browse_button)."""
        row = ttk.Frame(parent)
        row.pack(fill="x", padx=6, pady=3)
        self._mk_label(row, label_key, width=16).pack(side="left")
        entry = ttk.Entry(row, textvariable=var)
        entry.pack(side="left", fill="x", expand=True, padx=6)
        btn = self._mk_button(row, "browse", lambda: browse_fn(var))
        btn.pack(side="left")
        return entry, btn

    # ================= UI build =================
    def _build_ui(self):
        # ---- top bar: language + texture format ----
        top = ttk.Frame(self.root)
        top.pack(fill="x", padx=10, pady=(10, 0))

        self._mk_label(top, "language_label").pack(side="left")
        self._lang_map = {"English": "en", "한국어": "ko", "日本語": "ja"}
        _code_to_name = {v: k for k, v in self._lang_map.items()}
        self._lang_display = tk.StringVar(value=_code_to_name.get(self.lang.get(), "English"))
        lang_cb = ttk.Combobox(top, textvariable=self._lang_display,
                               values=list(self._lang_map.keys()),
                               state="readonly", width=10)
        lang_cb.pack(side="left", padx=(4, 18))
        lang_cb.bind("<<ComboboxSelected>>",
                     lambda e: self._change_language(self._lang_map[self._lang_display.get()]))

        self._mk_label(top, "format_label").pack(side="left")
        ttk.Combobox(top, textvariable=self.texture_format, values=TEXTURE_FORMATS,
                     state="readonly", width=18).pack(side="left", padx=6)

        # ---- status bar (bottom) ----
        self.status = ttk.Label(self.root, text=self.t("status_ready"),
                                relief=tk.SUNKEN, anchor="w")
        self.status.pack(side="bottom", fill="x", padx=10, pady=(0, 8))
        self._status_is_ready = True
        self._register(self._refresh_ready_status)

        # ---- log panel (bottom) ----
        logframe = self._mk_labelframe(self.root, "log")
        logframe.pack(side="bottom", fill="x", padx=10, pady=(0, 4))
        self.log_text = scrolledtext.ScrolledText(logframe, height=9, wrap="word",
                                                  state="disabled")
        self.log_text.pack(side="left", fill="both", expand=True, padx=4, pady=4)
        self._mk_button(logframe, "clear_log", self._clear_log).pack(side="right",
                                                                     padx=4, pady=4,
                                                                     anchor="n")

        # ---- notebook ----
        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=10, pady=10)

        single = ttk.Frame(nb)
        batch = ttk.Frame(nb)
        nb.add(single, text=self.t("tab_single"))
        nb.add(batch, text=self.t("tab_batch"))
        self._register(lambda nb=nb, s=single: nb.tab(s, text=self.t("tab_single")))
        self._register(lambda nb=nb, b=batch: nb.tab(b, text=self.t("tab_batch")))
        self._register(lambda: self.root.title(self.t("title")))

        self._build_single_tab(single)
        self._build_batch_tab(batch)

    def _refresh_ready_status(self):
        if getattr(self, "_status_is_ready", False):
            self.status.config(text=self.t("status_ready"))

    # ================= Single tab =================
    def _build_single_tab(self, parent):
        controls = ttk.Frame(parent)
        controls.pack(side="top", fill="x")

        self._file_row(controls, "bundle_file", self.single_bundle, self._browse_bundle)

        # Image source
        src = self._mk_labelframe(controls, "image_source", padding=8)
        src.pack(fill="x", padx=6, pady=(6, 2))
        self._mk_radio(src, "src_folder", self.single_src_mode, "folder",
                       command=self._single_on_srcmode).pack(anchor="w")
        self.single_folder_entry, self.single_folder_browse = self._file_row(
            src, "image_folder", self.single_images, self._browse_folder)
        self.single_images.trace_add("write",
                                     lambda *a: self._single_update_replacement())
        self._mk_radio(src, "src_single", self.single_src_mode, "single",
                       command=self._single_on_srcmode).pack(anchor="w", pady=(6, 0))
        self.single_file_entry, self.single_file_browse = self._file_row(
            src, "single_image_file", self.single_image_file, self._browse_image_file)

        # Output
        out = self._mk_labelframe(controls, "output", padding=8)
        out.pack(fill="x", padx=6, pady=(2, 4))
        self._mk_radio(out, "out_same", self.single_out_mode, "same",
                       command=self._single_on_outmode).pack(anchor="w")
        srow = ttk.Frame(out)
        srow.pack(fill="x", padx=20, pady=2)
        self._mk_label(srow, "suffix_label", width=10).pack(side="left")
        self.single_suffix_entry = ttk.Entry(srow, textvariable=self.single_suffix, width=20)
        self.single_suffix_entry.pack(side="left")
        self._mk_radio(out, "out_custom", self.single_out_mode, "custom",
                       command=self._single_on_outmode).pack(anchor="w", pady=(6, 0))
        self.single_output_entry, self.single_output_browse = self._file_row(
            out, "output_bundle", self.single_output, self._browse_save_file)

        # Import button at the bottom of the tab.
        self._mk_button(parent, "import_single", self._run_single, width=20).pack(
            side="bottom", pady=8)

        # Body: texture list (left) + previews (right)
        body = ttk.Frame(parent)
        body.pack(side="top", fill="both", expand=True, padx=6, pady=6)

        left = self._mk_labelframe(body, "textures")
        left.pack(side="left", fill="both", expand=True, padx=(0, 6))
        self._mk_button(left, "load_textures", self._preview_single).pack(
            fill="x", padx=4, pady=4)
        lf = ttk.Frame(left)
        lf.pack(fill="both", expand=True, padx=4, pady=(0, 4))
        sb = ttk.Scrollbar(lf)
        sb.pack(side="right", fill="y")
        self.single_list = tk.Listbox(lf, height=12, yscrollcommand=sb.set,
                                      exportselection=False)
        self.single_list.pack(side="left", fill="both", expand=True)
        sb.config(command=self.single_list.yview)
        self.single_list.bind("<<ListboxSelect>>", self._on_single_select)

        right = ttk.Frame(body)
        right.pack(side="right", fill="y")
        cur_frame = self._mk_labelframe(right, "current_texture")
        cur_frame.pack(side="left", padx=4)
        self.canvas_current = tk.Canvas(cur_frame, width=PREVIEW_W, height=PREVIEW_H,
                                        bg="#2b2b2b", highlightthickness=0)
        self.canvas_current.pack(padx=4, pady=4)
        rep_frame = self._mk_labelframe(right, "replacement_image")
        rep_frame.pack(side="left", padx=4)
        self.canvas_replace = tk.Canvas(rep_frame, width=PREVIEW_W, height=PREVIEW_H,
                                        bg="#2b2b2b", highlightthickness=0)
        self.canvas_replace.pack(padx=4, pady=4)
        self._render(self.canvas_current, None)
        self._render(self.canvas_replace, None)

    # ================= Batch tab =================
    def _build_batch_tab(self, parent):
        sec = self._mk_labelframe(parent, "bundle_selection", padding=8)
        sec.pack(fill="both", expand=True, padx=6, pady=6)

        bar = ttk.Frame(sec)
        bar.pack(fill="x", pady=(0, 6))
        self._mk_button(bar, "add_files", self._add_bundle_files, width=18).pack(side="left", padx=3)
        self._mk_button(bar, "add_folder", self._add_bundle_folder, width=16).pack(side="left", padx=3)
        self._mk_button(bar, "clear_all", self._clear_bundles, width=14).pack(side="left", padx=3)
        self._mk_check(bar, "recursive", self.batch_recursive).pack(side="left", padx=12)

        lf = ttk.Frame(sec)
        lf.pack(fill="both", expand=True)
        sb = ttk.Scrollbar(lf)
        sb.pack(side="right", fill="y")
        self.batch_list = tk.Listbox(lf, height=10, yscrollcommand=sb.set)
        self.batch_list.pack(side="left", fill="both", expand=True)
        sb.config(command=self.batch_list.yview)

        self._file_row(parent, "image_root", self.batch_images, self._browse_folder)

        out = self._mk_labelframe(parent, "output", padding=8)
        out.pack(fill="x", padx=6, pady=4)
        self._mk_radio(out, "out_same_each", self.batch_out_mode, "same",
                       command=self._batch_on_outmode).pack(anchor="w")
        self._mk_radio(out, "out_to_folder", self.batch_out_mode, "folder",
                       command=self._batch_on_outmode).pack(anchor="w", pady=(4, 0))
        self.batch_output_entry, self.batch_output_browse = self._file_row(
            out, "output_folder", self.batch_output, self._browse_folder)
        orow = ttk.Frame(out)
        orow.pack(fill="x", padx=20, pady=2)
        self._mk_label(orow, "suffix_label", width=10).pack(side="left")
        ttk.Entry(orow, textvariable=self.batch_suffix, width=20).pack(side="left")
        self.batch_preserve_check = self._mk_check(orow, "preserve_tree",
                                                   self.batch_preserve_tree)
        self.batch_preserve_check.pack(side="left", padx=16)

        self._mk_button(parent, "import_batch", self._run_batch, width=20).pack(pady=8)

    # ================= state toggles =================
    @staticmethod
    def _set_state(widgets, enabled):
        st = "normal" if enabled else "disabled"
        for w in widgets:
            try:
                w.config(state=st)
            except Exception:
                pass

    def _single_on_srcmode(self):
        folder = self.single_src_mode.get() == "folder"
        self._set_state([self.single_folder_entry, self.single_folder_browse], folder)
        self._set_state([self.single_file_entry, self.single_file_browse], not folder)
        self._single_update_replacement()

    def _single_on_outmode(self):
        same = self.single_out_mode.get() == "same"
        self._set_state([self.single_suffix_entry], same)
        self._set_state([self.single_output_entry, self.single_output_browse], not same)
        self._single_recompute_output()

    def _batch_on_outmode(self):
        to_folder = self.batch_out_mode.get() == "folder"
        self._set_state([self.batch_output_entry, self.batch_output_browse,
                         self.batch_preserve_check], to_folder)

    def _single_compute_output(self):
        if self.single_out_mode.get() == "same":
            bundle = self.single_bundle.get()
            if not bundle:
                return ""
            suffix = self.single_suffix.get() or DEFAULT_SUFFIX
            stem, ext = os.path.splitext(os.path.basename(bundle))
            return os.path.join(os.path.dirname(bundle), stem + suffix + ext)
        return self.single_output.get()

    def _single_recompute_output(self):
        if self.single_out_mode.get() == "same":
            computed = self._single_compute_output()
            # Avoid feedback loop: only set if changed.
            if self.single_output.get() != computed:
                self.single_output.set(computed)

    # ================= browse handlers =================
    def _browse_bundle(self, var):
        fp = filedialog.askopenfilename(
            title="Select Bundle File",
            filetypes=[("Unity bundle", "*.unity *.unity3d *.bundle *.ab *.assets"),
                       ("All Files", "*.*")])
        if fp:
            var.set(fp)

    def _browse_folder(self, var):
        d = filedialog.askdirectory(title="Select Folder")
        if d:
            var.set(d)

    def _browse_save_file(self, var):
        fp = filedialog.asksaveasfilename(title="Save Output Bundle",
                                          defaultextension=".*",
                                          filetypes=[("All Files", "*.*")])
        if fp:
            var.set(fp)

    def _browse_image_file(self, var):
        fp = filedialog.askopenfilename(
            title="Select Image File",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp *.tga"), ("All Files", "*.*")])
        if not fp:
            return
        var.set(fp)
        # Convenience: if the file name matches a texture, auto-select it.
        stem = os.path.splitext(os.path.basename(fp))[0]
        for i, data in enumerate(self.single_tex_data):
            if getattr(data, "m_Name", "") == stem:
                self.single_list.selection_clear(0, tk.END)
                self.single_list.selection_set(i)
                self.single_list.see(i)
                self._on_single_select()
                break
        self._single_update_replacement()

    def _add_bundle_files(self):
        files = filedialog.askopenfilenames(
            title="Select Bundle Files (Multiple)",
            filetypes=[("Unity bundle", "*.unity *.unity3d *.bundle *.ab *.assets"),
                       ("All Files", "*.*")])
        if not files:
            return
        added = 0
        for f in files:
            if f not in self.batch_bundles:
                self.batch_bundles.append(f)
                self.batch_list.insert(tk.END, f)
                added += 1
        self._set_status(self.t("added_files", n=added, total=len(self.batch_bundles)))

    def _add_bundle_folder(self):
        folder = filedialog.askdirectory(title="Select Folder containing bundles")
        if not folder:
            return
        found = list(iter_bundle_files(folder, self.batch_recursive.get()))
        added = 0
        for f in found:
            if f not in self.batch_bundles:
                self.batch_bundles.append(f)
                self.batch_list.insert(tk.END, f)
                added += 1
        self._set_status(self.t("added_folder", n=added, total=len(self.batch_bundles)))

    def _clear_bundles(self):
        self.batch_bundles.clear()
        self.batch_list.delete(0, tk.END)
        self._set_status(self.t("cleared"))

    # ================= preview =================
    @staticmethod
    def _make_checker(size, light=(225, 225, 225), dark=(170, 170, 170), cell=12):
        w, h = size
        bg = Image.new("RGBA", (w, h), light + (255,))
        draw = ImageDraw.Draw(bg)
        for y in range(0, h, cell):
            for x in range(0, w, cell):
                if (x // cell + y // cell) % 2:
                    draw.rectangle([x, y, x + cell, y + cell], fill=dark + (255,))
        return bg

    def _render(self, canvas, pil, error=None, caption=None):
        """Draw a PIL image (composited over a checkerboard) onto a canvas."""
        canvas.delete("all")
        W, H = PREVIEW_W, PREVIEW_H
        if error:
            canvas.create_text(W // 2, H // 2, text=error, fill="#ff8a80",
                               width=W - 20, justify="center")
            canvas.image = None
            return
        if pil is None:
            canvas.create_text(W // 2, H // 2, text=self.t("no_image"), fill="#9e9e9e")
            canvas.image = None
            return
        try:
            img = pil.convert("RGBA")
            disp = img.copy()
            disp.thumbnail((W - 10, H - 30))
            base = self._make_checker(disp.size)
            base.alpha_composite(disp)
            photo = ImageTk.PhotoImage(base)
            canvas.image = photo  # keep a reference (avoid GC)
            canvas.create_image(W // 2, (H - 18) // 2, image=photo)
            cap = caption or "{}x{}".format(img.width, img.height)
            canvas.create_text(W // 2, H - 12,
                               text="{}  ({}x{})".format(cap, img.width, img.height)
                               if caption else cap,
                               fill="#e0e0e0")
        except Exception as e:
            self._render(canvas, None, error=self.t("decode_failed", err=e))

    def _preview_single(self):
        path = self.single_bundle.get()
        if not path or not os.path.exists(path):
            messagebox.showerror(self.t("err_title"), self.t("err_select_bundle"))
            return
        try:
            env = UnityPy.load(path)
            self.single_list.delete(0, tk.END)
            self.single_tex_data = []
            for obj in env.objects:
                if obj.type.name == "Texture2D":
                    data = obj.read()
                    self.single_tex_data.append(data)
                    fmt = str(getattr(data, "m_TextureFormat", "")).split(".")[-1]
                    self.single_list.insert(
                        tk.END, "{}  ({}x{}, {})".format(
                            getattr(data, "m_Name", "?"),
                            getattr(data, "m_Width", 0),
                            getattr(data, "m_Height", 0), fmt))
            count = len(self.single_tex_data)
            self._set_status(self.t("found_textures", count=count))
            self.log(self.t("found_textures", count=count))
            if count == 0:
                self.log(self.t("no_textures_found"))
            self._render(self.canvas_current, None)
            self._single_update_replacement()
        except Exception as e:
            self.log(traceback.format_exc())
            messagebox.showerror(self.t("err_title"), self.t("preview_failed", err=e))

    def _on_single_select(self, event=None):
        sel = self.single_list.curselection()
        if not sel:
            return
        data = self.single_tex_data[sel[0]]
        try:
            cur = data.image
            self._render(self.canvas_current, cur, caption=getattr(data, "m_Name", ""))
        except Exception as e:
            self._render(self.canvas_current, None, error=self.t("decode_failed", err=e))
            self.log("decode current '{}': {}".format(getattr(data, "m_Name", "?"), e))
        self._single_update_replacement(data)

    def _single_update_replacement(self, data=None):
        if data is None:
            sel = self.single_list.curselection()
            data = self.single_tex_data[sel[0]] if (sel and self.single_tex_data) else None

        if self.single_src_mode.get() == "folder":
            folder = self.single_images.get()
            name = getattr(data, "m_Name", None) if data else None
            img_path = find_image_by_name(folder, name)
            if img_path:
                try:
                    self._render(self.canvas_replace, open_image_checked(img_path),
                                 caption=os.path.basename(img_path))
                except Exception as e:
                    self._render(self.canvas_replace, None, error=str(e))
            else:
                self._render(self.canvas_replace, None,
                             error=self.t("no_match") if (folder and name) else None)
        else:
            img_path = self.single_image_file.get()
            if img_path and os.path.exists(img_path):
                try:
                    self._render(self.canvas_replace, open_image_checked(img_path),
                                 caption=os.path.basename(img_path))
                except Exception as e:
                    self._render(self.canvas_replace, None, error=str(e))
            else:
                self._render(self.canvas_replace, None)

    # ================= status / log (thread-safe) =================
    def _ui(self, fn):
        self.root.after(0, fn)

    def _set_status(self, text, ready=False):
        def do():
            self._status_is_ready = ready
            self.status.config(text=text)
        self._ui(do)

    def log(self, text):
        def do():
            self.log_text.configure(state="normal")
            self.log_text.insert("end", text + "\n")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        self._ui(do)

    def _clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    @staticmethod
    def _format_errors(errors, limit=8):
        lines = []
        for (name, path, msg, tb) in errors[:limit]:
            lines.append("- {}: {}".format(name, msg))
        return "\n".join(lines)

    # ================= runners =================
    def _run_single(self):
        bundle = self.single_bundle.get()
        if not bundle or not os.path.exists(bundle):
            messagebox.showerror(self.t("err_title"), self.t("err_select_bundle"))
            return
        fmt = self.texture_format.get()

        if self.single_src_mode.get() == "folder":
            folder = self.single_images.get()
            if not folder or not os.path.isdir(folder):
                messagebox.showerror(self.t("err_title"), self.t("err_select_image_folder"))
                return
            resolver = lambda name, f=folder: find_image_by_name(f, name)
        else:
            sel = self.single_list.curselection()
            if not sel or not self.single_tex_data:
                messagebox.showerror(self.t("err_title"), self.t("err_no_texture_selected"))
                return
            target = getattr(self.single_tex_data[sel[0]], "m_Name", "")
            img_file = self.single_image_file.get()
            if not img_file or not os.path.exists(img_file):
                messagebox.showerror(self.t("err_title"), self.t("err_select_image_file"))
                return
            resolver = lambda name, t=target, p=img_file: (p if name == t else None)

        # Resolve / guard output path.
        if self.single_out_mode.get() == "same" and not (self.single_suffix.get() or "").strip():
            self.single_suffix.set(DEFAULT_SUFFIX)
            messagebox.showwarning(self.t("warn_title"),
                                   self.t("err_empty_suffix", suffix=DEFAULT_SUFFIX))
        out_path = self._single_compute_output()
        if not out_path:
            messagebox.showerror(self.t("err_title"), self.t("err_select_output"))
            return
        if os.path.abspath(out_path) == os.path.abspath(bundle):
            messagebox.showerror(self.t("err_title"), self.t("err_overwrite_input"))
            return

        def job():
            try:
                self._set_status(self.t("importing_single"))
                self.log("=" * 60)
                imported, skipped, errors = process_bundle(
                    bundle, out_path, resolver, fmt, self.log)
                self._report_single(imported, skipped, errors, out_path)
            except Exception as e:
                self.log(traceback.format_exc())
                self._set_status(self.t("status_error"))
                self._ui(lambda e=e: messagebox.showerror(
                    self.t("err_title"), self.t("fatal_error", err=e)))

        threading.Thread(target=job, daemon=True).start()

    def _report_single(self, imported, skipped, errors, out_path):
        self._set_status(self.t("done_single_status", n=imported))

        def show():
            if errors:
                detail = self._format_errors(errors)
                more = "" if len(errors) <= 8 else self.t("more_errors", n=len(errors) - 8)
                messagebox.showwarning(
                    self.t("done_with_errors_title"),
                    self.t("done_single_errors", imported=imported, skipped=skipped,
                           errors=len(errors), path=out_path)
                    + "\n" + detail + more + "\n\n" + self.t("see_log"))
            else:
                messagebox.showinfo(
                    self.t("done_title"),
                    self.t("done_single", imported=imported, skipped=skipped, path=out_path))

        self._ui(show)

    def _run_batch(self):
        if not self.batch_bundles:
            messagebox.showerror(self.t("err_title"), self.t("err_no_bundles"))
            return
        imgs = self.batch_images.get()
        if not imgs or not os.path.isdir(imgs):
            messagebox.showerror(self.t("err_title"), self.t("err_select_image_root"))
            return

        out_mode = self.batch_out_mode.get()
        outdir = self.batch_output.get()
        if out_mode == "folder" and not outdir:
            messagebox.showerror(self.t("err_title"), self.t("err_select_output_folder"))
            return

        suffix = (self.batch_suffix.get() or "").strip() or DEFAULT_SUFFIX
        keep_tree = self.batch_preserve_tree.get()
        fmt = self.texture_format.get()
        bundles = list(self.batch_bundles)

        def compute_out(bp):
            stem, ext = os.path.splitext(os.path.basename(bp))
            if out_mode == "same":
                return os.path.join(os.path.dirname(bp), stem + suffix + ext)
            if keep_tree:
                base = os.path.dirname(bundles[0])
                rel = os.path.relpath(bp, start=base)
                rstem, rext = os.path.splitext(rel)
                return os.path.join(outdir, rstem + suffix + rext)
            return os.path.join(outdir, stem + suffix + ext)

        def job():
            total_imported = total_skipped = processed = failed = 0
            all_errors = []
            self._set_status(self.t("importing_batch"))
            self.log("=" * 60)
            for i, bp in enumerate(bundles, 1):
                outp = compute_out(bp)
                if os.path.abspath(outp) == os.path.abspath(bp):
                    self.log("! skip (would overwrite input): {}".format(bp))
                    all_errors.append((bp, None, "would overwrite input", ""))
                    failed += 1
                    continue
                try:
                    imp, skp, errs = process_bundle(
                        bp, outp, lambda name, f=imgs: find_image_by_name(f, name),
                        fmt, self.log)
                    total_imported += imp
                    total_skipped += skp
                    all_errors.extend(errs)
                    processed += 1
                    self._set_status(self.t("batch_progress", i=i, total=len(bundles),
                                            path=os.path.basename(outp), n=imp))
                except Exception as e:
                    self.log(traceback.format_exc())
                    all_errors.append((bp, None, str(e), traceback.format_exc()))
                    failed += 1
                    self._set_status(self.t("batch_failed_item",
                                            path=os.path.basename(bp)))
            self._report_batch(processed, failed, total_imported, total_skipped, all_errors)

        threading.Thread(target=job, daemon=True).start()

    def _report_batch(self, processed, failed, imported, skipped, errors):
        self._set_status(self.t("done_batch_status", imported=imported, processed=processed))

        def show():
            if errors:
                detail = self._format_errors(errors)
                more = "" if len(errors) <= 8 else self.t("more_errors", n=len(errors) - 8)
                messagebox.showwarning(
                    self.t("done_with_errors_title"),
                    self.t("done_batch_errors", processed=processed, failed=failed,
                           imported=imported, skipped=skipped, errors=len(errors))
                    + "\n" + detail + more + "\n\n" + self.t("see_log"))
            else:
                messagebox.showinfo(
                    self.t("done_title"),
                    self.t("done_batch", processed=processed, failed=failed,
                           imported=imported, skipped=skipped))

        self._ui(show)


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
