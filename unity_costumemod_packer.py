# unity_costumemod_packer.py (modified)
# Adds a "modded -> suit" library workflow (Termux text menu) on top of the
# original GUI packer, and makes the script importable/runnable where tkinter
# isn't installed (e.g. Termux).

import os
import zipfile
import io
import re
import threading
import subprocess
import sys
import struct
import lzma
import argparse
import base64
import tempfile
import platform as _platform

# --- self-contained multi-language support (English default; 한국어 / 日本語) ---
# Translations are embedded so this single file works on its own; the chosen
# language is remembered/shared via ~/.config/sifas_modding_tools/config.json.
import json as _json


class _LangStore:
    @staticmethod
    def _path():
        if os.name == "nt":
            base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Roaming")
        else:
            base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
        return os.path.join(base, "sifas_modding_tools", "config.json")

    def get_language(self):
        try:
            with open(self._path(), encoding="utf-8") as f:
                return _json.load(f).get("language")
        except Exception:
            return None

    def set_language(self, code):
        try:
            p = self._path()
            os.makedirs(os.path.dirname(p), exist_ok=True)
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
_LANG_NAMES = (("en", "English"), ("ko", "한국어"), ("ja", "日本語"))
_PK_PLATFORM_NOTE = ("Platform is read from each bundle's Unity header. Pairs are matched by "
                     "filename ignoring apk/android/ios tokens.")
_PK_DONE_MSG = "Processing completed:\n✅ Successful: {succ}\n❌ Failed: {fail}\n\n{loc}\n\nOpen output folder?"
_TRANSLATIONS = {
    "ko": {
        "Language": "언어",
        "Unity Asset Bundle Mod Packer": "Unity 에셋 번들 모드 패커",
        "Unity Asset Bundle Mod Packer (Rina Auto-Pair)": "Unity 에셋 번들 모드 패커 (리나 자동 페어링)",
        " [UnityPy installation required]": " [UnityPy 설치 필요]",
        "Install required modules": "필수 모듈 설치",
        "Processing Mode": "처리 모드",
        "Single File Mode": "단일 파일 모드",
        "Batch Mode (Multiple Files)": "일괄 모드 (여러 파일)",
        "File Selection": "파일 선택",
        "Asset Bundle File:": "에셋 번들 파일:",
        "Browse": "찾아보기",
        "📁 Add Files": "📁 파일 추가",
        "📂 Add Folder": "📂 폴더 추가",
        "📥 Scan 'modded'": "📥 'modded' 스캔",
        "🗑️ Clear All": "🗑️ 전체 비우기",
        "Preview": "미리보기",
        "select a file": "파일을 선택하세요",
        "Remove Selected": "선택 항목 제거",
        "Output Settings": "출력 설정",
        "Output to location where target Bundle exists": "대상 번들이 있는 위치에 출력",
        "Output Directory:": "출력 디렉터리:",
        "Settings": "설정",
        "Thumbnail Size:": "썸네일 크기:",
        "px": "px",
        "Auto-detect Character ID (texture/filename)": "캐릭터 ID 자동 감지 (텍스처/파일명)",
        "Manual Character ID:": "수동 캐릭터 ID:",
        "Platform (Android / iOS)": "플랫폼 (Android / iOS)",
        "Append platform suffix to zip name (_apk / _ios)": "zip 이름에 플랫폼 접미사 추가 (_apk / _ios)",
        "Combine detected Android+iOS pairs into one zip (name_apk_ios.zip)":
            "감지된 Android+iOS 쌍을 하나의 zip으로 결합 (name_apk_ios.zip)",
        _PK_PLATFORM_NOTE: "플랫폼은 각 번들의 Unity 헤더에서 읽습니다. 쌍은 apk/android/ios 토큰을 무시한 파일명으로 매칭됩니다.",
        "🚀 Create Mod Package(s)": "🚀 모드 패키지 생성",
        "🚀 Create Mod Package(s) (UnityPy/Pillow required)": "🚀 모드 패키지 생성 (UnityPy/Pillow 필요)",
        "🚀 Create Mod Package": "🚀 모드 패키지 생성",
        "🚀 Create Mod Packages": "🚀 모드 패키지 생성",
        "🔄 Processing...": "🔄 처리 중...",
        "Progress": "진행 상황",
        "Overall Progress:": "전체 진행:",
        "0 / 0 files": "0 / 0 파일",
        "Current File:": "현재 파일:",
        "Ready": "준비됨",
        "Processing Log": "처리 로그",
        "Select Asset Bundle File": "에셋 번들 파일 선택",
        "Select Asset Bundle Files": "에셋 번들 파일 선택",
        "Select Folder": "폴더 선택",
        "Select Output Directory": "출력 디렉터리 선택",
        "Scan 'modded'": "'modded' 스캔",
        "No Unity asset bundles found in:\n{modded}": "다음 위치에서 Unity 에셋 번들을 찾을 수 없습니다:\n{modded}",
        "Error": "오류",
        "Please add files.": "파일을 추가하세요.",
        "Please select valid files.": "올바른 파일을 선택하세요.",
        "Processing Complete": "처리 완료",
        "Saved to each Bundle file location.": "각 번들 파일 위치에 저장했습니다.",
        "Output location: {folder}": "출력 위치: {folder}",
        _PK_DONE_MSG: "처리 완료:\n✅ 성공: {succ}\n❌ 실패: {fail}\n\n{loc}\n\n출력 폴더를 여시겠습니까?",
    },
    "ja": {
        "Language": "言語",
        "Unity Asset Bundle Mod Packer": "Unity アセットバンドル MOD パッカー",
        "Unity Asset Bundle Mod Packer (Rina Auto-Pair)": "Unity アセットバンドル MOD パッカー（りな自動ペア）",
        " [UnityPy installation required]": " [UnityPy のインストールが必要]",
        "Install required modules": "必要なモジュールをインストール",
        "Processing Mode": "処理モード",
        "Single File Mode": "単一ファイルモード",
        "Batch Mode (Multiple Files)": "一括モード（複数ファイル）",
        "File Selection": "ファイル選択",
        "Asset Bundle File:": "アセットバンドルファイル:",
        "Browse": "参照",
        "📁 Add Files": "📁 ファイルを追加",
        "📂 Add Folder": "📂 フォルダを追加",
        "📥 Scan 'modded'": "📥 'modded' をスキャン",
        "🗑️ Clear All": "🗑️ すべてクリア",
        "Preview": "プレビュー",
        "select a file": "ファイルを選択",
        "Remove Selected": "選択を削除",
        "Output Settings": "出力設定",
        "Output to location where target Bundle exists": "対象バンドルがある場所に出力",
        "Output Directory:": "出力ディレクトリ:",
        "Settings": "設定",
        "Thumbnail Size:": "サムネイルサイズ:",
        "px": "px",
        "Auto-detect Character ID (texture/filename)": "キャラID自動検出（テクスチャ/ファイル名）",
        "Manual Character ID:": "手動キャラID:",
        "Platform (Android / iOS)": "プラットフォーム（Android / iOS）",
        "Append platform suffix to zip name (_apk / _ios)": "zip 名にプラットフォーム接尾辞を付加 (_apk / _ios)",
        "Combine detected Android+iOS pairs into one zip (name_apk_ios.zip)":
            "検出した Android+iOS ペアを1つの zip に結合 (name_apk_ios.zip)",
        _PK_PLATFORM_NOTE: "プラットフォームは各バンドルの Unity ヘッダーから読み取ります。ペアは apk/android/ios トークンを無視したファイル名で照合します。",
        "🚀 Create Mod Package(s)": "🚀 MOD パッケージを作成",
        "🚀 Create Mod Package(s) (UnityPy/Pillow required)": "🚀 MOD パッケージを作成（UnityPy/Pillow が必要）",
        "🚀 Create Mod Package": "🚀 MOD パッケージを作成",
        "🚀 Create Mod Packages": "🚀 MOD パッケージを作成",
        "🔄 Processing...": "🔄 処理中...",
        "Progress": "進捗",
        "Overall Progress:": "全体の進捗:",
        "0 / 0 files": "0 / 0 ファイル",
        "Current File:": "現在のファイル:",
        "Ready": "準備完了",
        "Processing Log": "処理ログ",
        "Select Asset Bundle File": "アセットバンドルファイルを選択",
        "Select Asset Bundle Files": "アセットバンドルファイルを選択",
        "Select Folder": "フォルダを選択",
        "Select Output Directory": "出力ディレクトリを選択",
        "Scan 'modded'": "'modded' をスキャン",
        "No Unity asset bundles found in:\n{modded}": "次の場所に Unity アセットバンドルが見つかりません:\n{modded}",
        "Error": "エラー",
        "Please add files.": "ファイルを追加してください。",
        "Please select valid files.": "有効なファイルを選択してください。",
        "Processing Complete": "処理完了",
        "Saved to each Bundle file location.": "各バンドルファイルの場所に保存しました。",
        "Output location: {folder}": "出力場所: {folder}",
        _PK_DONE_MSG: "処理が完了しました:\n✅ 成功: {succ}\n❌ 失敗: {fail}\n\n{loc}\n\n出力フォルダを開きますか？",
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


# NOTE: on Termux the native texture decoders (astc-encoder-py / texture2ddecoder
# / etcpak) are unreliable - depending on the device/build they raise, fail to
# load libfmod, or hard-crash the whole process with SIGILL ("Illegal
# instruction") the moment a texture is decoded (the crash is at DECODE time, not
# at `import UnityPy` - the native libs are imported lazily on the first decode).
#
# To still get REAL thumbnails there without risking the run, texture decoding on
# Termux is now done in a throwaway CHILD PROCESS (see _decode_mode /
# _decode_texture_via_subprocess): if the native decoder crashes, only the child
# dies and we fall back to a name thumbnail instead of taking the packer down with
# it. So decoding is attempted by default everywhere; set PACKER_DECODE_THUMBNAILS=0
# to skip it (fast, name-only thumbnails). If the child keeps crashing on your
# device, rebuilding the decoders from source usually fixes it (prebuilt wheels can
# be glibc/CPU-incompatible with Termux):
#     pip install --force-reinstall --no-binary :all: astc-encoder-py texture2ddecoder etcpak

# UnityPy's export package eagerly imports AudioClipConverter, which runs
# `import fmod_toolkit` at module load. fmod_toolkit then tries to dlopen a
# native libfmod.so that isn't bundled for Termux/arm64, so even *texture*
# decoding fails with "libfmod.so not found". This packer never touches audio,
# so we stub fmod_toolkit with a harmless dummy that satisfies the import
# without loading any native library.
if "fmod_toolkit" not in sys.modules:
    import types as _types
    _fmod_stub = _types.ModuleType("fmod_toolkit")

    def _fmod_unavailable(*args, **kwargs):
        raise RuntimeError("fmod_toolkit is stubbed (audio export is not supported here)")

    _fmod_stub.raw_to_wav = _fmod_unavailable
    sys.modules["fmod_toolkit"] = _fmod_stub

# Absolute path to this script, captured at import time so the decode-worker
# subprocess can re-launch it even if the cwd changes later.
try:
    _THIS_FILE = os.path.abspath(__file__)
except NameError:
    _THIS_FILE = os.path.abspath(sys.argv[0])

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except Exception:
    tk = None
    filedialog = messagebox = ttk = None


def is_termux():
    if "com.termux" in (os.environ.get("PREFIX", "") + os.environ.get("HOME", "")):
        return True
    return os.path.isdir("/data/data/com.termux")


def _env_flag(name):
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def _decode_mode():
    """How thumbnail texture decoding should run in THIS process.

    Returns one of:
      'off'         - never decode; use name-only thumbnails (fast, can't crash).
      'inprocess'   - decode directly (reliable on desktop).
      'subprocess'  - decode in a throwaway child so a native-decoder SIGILL only
                      kills the child, not the packer (the default on Termux).

    Overrides:
      PACKER_DECODE_THUMBNAILS=0  -> 'off'
      PACKER_DECODE_INPROCESS=1   -> force 'inprocess' even on Termux (debug)
      PACKER_DECODE_ISOLATE=1     -> force 'subprocess' even on desktop
    """
    if os.environ.get("PACKER_DECODE_THUMBNAILS", "").strip().lower() in ("0", "false", "no", "off"):
        return "off"
    if _env_flag("PACKER_DECODE_INPROCESS"):
        return "inprocess"
    if _env_flag("PACKER_DECODE_ISOLATE") or is_termux():
        return "subprocess"
    return "inprocess"


def _patch_platform_for_decode():
    """archspec (pulled in lazily by astc-encoder-py on the first decode) doesn't
    recognise Termux's platform.system() == "Android" and raises. Present as
    "Linux" so the decoder can initialise. Detection uses $PREFIX, so this does
    not affect is_termux(). Safe to call repeatedly; a no-op off Android."""
    if _platform.system() == "Android":
        _platform.system = lambda: "Linux"


def gui_available():
    if tk is None:
        return False
    if is_termux():
        return False
    if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
        return False
    return True


def default_sukusta_dir(name):
    """sukusta/<name> path. The SUKUSTA_DIR env var overrides the base.
    Termux uses shared Downloads; otherwise ~/sukusta."""
    base = os.environ.get("SUKUSTA_DIR")
    if base:
        return os.path.join(os.path.expanduser(base), name)
    if is_termux():
        return os.path.expanduser(f"~/storage/downloads/sukusta/{name}")
    return os.path.expanduser(f"~/sukusta/{name}")

# ============================================================
# Unity 에셋번들 플랫폼 감지 (Android / iOS)
# ------------------------------------------------------------
# SerializedFile 메타데이터의 m_TargetPlatform으로 판별한다.
#   13 = Android, 9 = iOS(iPhone)
# UnityFS 블록(LZ4/LZMA) 해제는 외부 패키지 없이 동작하도록 순수
# 파이썬으로 구현했고, 실패 시 UnityPy 폴백을 시도한다.
# (costume_addon_installer.py의 감지기와 동일한 로직)
# ============================================================

UNITY_PLATFORM_NAMES = {13: 'android', 9: 'ios'}
PLATFORM_ZIP_SUFFIX = {'android': 'apk', 'ios': 'ios'}
PLATFORM_NAME_TOKENS = {'android': ('apk', 'android'), 'ios': ('ios',)}

def _lz4_block_decompress(data, uncompressed_size):
    """LZ4 블록 포맷 디코더 (프레임 헤더 없음)."""
    out = bytearray()
    i = 0
    n = len(data)
    while i < n and len(out) < uncompressed_size:
        token = data[i]; i += 1
        lit_len = token >> 4
        if lit_len == 15:
            while True:
                b = data[i]; i += 1
                lit_len += b
                if b != 255:
                    break
        out += data[i:i + lit_len]
        i += lit_len
        if i >= n or len(out) >= uncompressed_size:
            break
        offset = data[i] | (data[i + 1] << 8); i += 2
        match_len = token & 0xF
        if match_len == 15:
            while True:
                b = data[i]; i += 1
                match_len += b
                if b != 255:
                    break
        match_len += 4
        start = len(out) - offset
        for k in range(match_len):
            out.append(out[start + k])
    return bytes(out)

def _lzma_raw_decompress(data, uncompressed_size):
    """유니티 번들의 LZMA 블록(5바이트 props + raw 스트림) 디코더."""
    props = data[0]
    lc = props % 9
    rem = props // 9
    lp = rem % 5
    pb = rem // 5
    dict_size = struct.unpack('<I', data[1:5])[0]
    dec = lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=[
        {"id": lzma.FILTER_LZMA1, "lc": lc, "lp": lp, "pb": pb, "dict_size": dict_size}])
    return dec.decompress(data[5:], max_length=uncompressed_size)

def _decompress_bundle_block(data, uncompressed_size, compression):
    if compression == 0:
        return data[:uncompressed_size]
    if compression == 1:
        return _lzma_raw_decompress(data, uncompressed_size)
    if compression in (2, 3):  # LZ4 / LZ4HC
        return _lz4_block_decompress(data, uncompressed_size)
    raise ValueError(f"unsupported block compression {compression}")

def _read_cstring(buf, pos):
    end = buf.index(b'\x00', pos)
    return buf[pos:end], end + 1

def _read_cstring_file(f):
    out = bytearray()
    while True:
        b = f.read(1)
        if not b or b == b'\x00':
            return bytes(out)
        out += b

def _platform_from_serialized(buf):
    """SerializedFile 헤더/메타데이터에서 m_TargetPlatform을 읽는다."""
    if len(buf) < 24:
        return None
    metadata_size, file_size, version, data_offset = struct.unpack_from('>IIII', buf, 0)
    if not (9 <= version <= 99):
        return None
    pos = 16
    endianess = buf[pos]
    pos += 4  # endianess(1) + reserved(3)
    if version >= 22:
        pos += 4 + 8 + 8 + 8
    _, pos = _read_cstring(buf, pos)            # 유니티 버전 문자열
    fmt = '>i' if endianess else '<i'
    target_platform = struct.unpack_from(fmt, buf, pos)[0]
    return UNITY_PLATFORM_NAMES.get(target_platform)

def _platform_from_unityfs(f):
    """UnityFS 번들에서 첫 노드(SerializedFile)의 플랫폼을 읽는다."""
    header = f.read(8)
    if header[:7] != b'UnityFS':
        return None
    f.seek(8)
    bundle_version = struct.unpack('>I', f.read(4))[0]
    _read_cstring_file(f); _read_cstring_file(f)  # player/engine 버전
    total_size, comp_info_size, uncomp_info_size, flags = struct.unpack('>qIII', f.read(20))
    if bundle_version >= 7:
        pos = f.tell()
        f.seek((pos + 15) // 16 * 16)
    if flags & 0x80:  # blocksInfo가 파일 끝에 있음
        data_start = f.tell()
        f.seek(-comp_info_size, 2)
        blocks_info_raw = f.read(comp_info_size)
        f.seek(data_start)
    else:
        blocks_info_raw = f.read(comp_info_size)
    blocks_info = _decompress_bundle_block(blocks_info_raw, uncomp_info_size, flags & 0x3F)

    pos = 16  # uncompressedDataHash
    block_count = struct.unpack_from('>i', blocks_info, pos)[0]; pos += 4
    blocks = []
    for _ in range(block_count):
        u_size, c_size, b_flags = struct.unpack_from('>IIH', blocks_info, pos); pos += 10
        blocks.append((u_size, c_size, b_flags & 0x3F))
    node_count = struct.unpack_from('>i', blocks_info, pos)[0]; pos += 4
    nodes = []
    for _ in range(node_count):
        offset, size, n_flags = struct.unpack_from('>qqI', blocks_info, pos); pos += 20
        _, pos = _read_cstring(blocks_info, pos)
        nodes.append((offset, size))
    if not nodes:
        return None
    first_offset = min(n[0] for n in nodes)

    needed = first_offset + 4096
    stream = bytearray()
    for u_size, c_size, b_comp in blocks:
        stream += _decompress_bundle_block(f.read(c_size), u_size, b_comp)
        if len(stream) >= needed:
            break
    return _platform_from_serialized(bytes(stream[first_offset:first_offset + 4096]))

def detect_unity_platform(path):
    """순수 파이썬 감지기. 'android'/'ios' 또는 실패 시 None."""
    try:
        with open(path, 'rb') as f:
            head = f.read(8)
            f.seek(0)
            if head[:7] == b'UnityFS':
                return _platform_from_unityfs(f)
            return _platform_from_serialized(f.read(4096))
    except Exception:
        return None

def detect_platform_unitypy(path):
    """UnityPy 폴백 감지기 (설치돼 있을 때만)."""
    if UnityPy is None:
        return None
    try:
        env = UnityPy.load(path)
        candidates = []
        assets = getattr(env, 'assets', None) or []
        for sf in assets:
            tp = getattr(sf, 'target_platform', None)
            if tp is not None:
                candidates.append(int(tp))
        for val in candidates:
            if val in UNITY_PLATFORM_NAMES:
                return UNITY_PLATFORM_NAMES[val]
    except Exception:
        pass
    return None

def detect_bundle_platform(path):
    """플랫폼 감지: 순수 파서 우선, 실패하면 UnityPy 폴백."""
    plat = detect_unity_platform(path)
    if plat is None:
        plat = detect_platform_unitypy(path)
    return plat

def strip_platform_tokens(name_no_ext):
    """파일명에서 플랫폼 토큰(apk/android/ios)을 제거해 페어링 키를 만든다.

    인스톨러가 팩 파일명을 소문자 영숫자만 허용하므로 (밑줄 불가),
    '204suitapk'처럼 구분자 없이 끝에 붙은 토큰도 제거한다.
    """
    tokens = re.split(r'[_\-. ]+', name_no_ext.lower())
    kept = []
    for t in tokens:
        if not t:
            continue
        if t in ('apk', 'android', 'ios'):
            continue
        for suffix in ('android', 'apk', 'ios'):
            if t.endswith(suffix) and len(t) > len(suffix):
                t = t[:-len(suffix)]
                break
        kept.append(t)
    key = '_'.join(kept)
    return key if key else name_no_ext.lower()

def compute_zip_basename(bn_no_ext, platform, append_suffix):
    """출력 zip 이름(확장자 제외)을 계산한다.

    append_suffix가 켜져 있고 플랫폼이 판별됐으면 _apk/_ios를 붙인다.
    파일명에 이미 해당 플랫폼 토큰이 들어 있으면 (구분자 유무 무관)
    중복으로 붙이지 않는다.
    """
    if not append_suffix or platform not in PLATFORM_ZIP_SUFFIX:
        return bn_no_ext
    lowered = bn_no_ext.lower()
    tokens = re.split(r'[_\-. ]+', lowered)
    for tok in PLATFORM_NAME_TOKENS[platform]:
        if tok in tokens or lowered.endswith(tok):
            return bn_no_ext
    return f"{bn_no_ext}_{PLATFORM_ZIP_SUFFIX[platform]}"

def build_pack_jobs(masked_files, platforms, combine_pairs):
    """처리 작업 목록을 만든다.

    combine_pairs가 켜져 있으면, 플랫폼 토큰을 제거한 키가 같고
    정확히 (android 1개 + ios 1개)인 파일 쌍을 'pair' 작업으로 묶는다.
    반환: [('single', path) | ('pair', key, android_path, ios_path), ...]
    """
    if not combine_pairs:
        return [('single', p) for p in masked_files]

    groups = {}
    for p in masked_files:
        key = strip_platform_tokens(os.path.splitext(os.path.basename(p))[0])
        groups.setdefault(key, []).append(p)

    pair_of = {}   # path -> ('pair', key, android, ios)
    for key, paths in groups.items():
        androids = [p for p in paths if platforms.get(p) == 'android']
        ioses = [p for p in paths if platforms.get(p) == 'ios']
        if len(paths) == 2 and len(androids) == 1 and len(ioses) == 1:
            job = ('pair', key, androids[0], ioses[0])
            pair_of[androids[0]] = job
            pair_of[ioses[0]] = job

    jobs = []
    emitted = set()
    for p in masked_files:
        if p in pair_of:
            job = pair_of[p]
            if id(job) not in emitted:
                emitted.add(id(job))
                jobs.append(job)
        else:
            jobs.append(('single', p))
    return jobs


# -------- Dependency helpers --------
def _run_cmd(cmd):
    try:
        subprocess.check_call(cmd)
        return True
    except Exception:
        return False


def _termux_install_pillow():
    """Install Termux's prebuilt Pillow (pip can't compile it there: no libjpeg)."""
    print("[setup] Installing image library (Pillow) via Termux packages - "
          "one-time, no action needed...")
    if (_run_cmd(["pkg", "install", "-y", "python-pillow"])
            or _run_cmd(["apt", "install", "-y", "python-pillow"])):
        return
    _run_cmd(["apt", "update", "-y"])
    (_run_cmd(["pkg", "install", "-y", "python-pillow"])
     or _run_cmd(["apt", "install", "-y", "python-pillow"]))


def ensure_module(mod_name: str, pip_name: str):
    try:
        return __import__(mod_name)
    except ImportError:
        pass
    # On Termux, Pillow can't be pip-compiled (missing libjpeg); install the
    # prebuilt system package instead so it 'just works' with no manual steps.
    if pip_name.lower() == "pillow" and is_termux():
        _termux_install_pillow()
        try:
            return __import__(mod_name)
        except ImportError:
            pass
    try:
        print(f"[setup] Installing {pip_name} (first run only, can take a minute)...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", pip_name])
        return __import__(mod_name)
    except Exception:
        return None


def ensure_pillow():
    return ensure_module("PIL", "Pillow")


def ensure_unitypy():
    # UnityPy imports Pillow at import time, so make sure Pillow is present first.
    ensure_pillow()
    return ensure_module("UnityPy", "UnityPy")


PIL = ensure_pillow()
UnityPy = ensure_unitypy()

# -------- Texture extraction (body only, safe) --------
def extract_body_texture_with_unitypy(bundle_path: str, log=None):
    """Find a body Texture2D and return (name, png_bytes), else (name_or_None, None).

    Dispatches according to _decode_mode():
      - 'off'        : read only the texture *name* (for the character ID) and
                       leave the caller to build a name thumbnail.
      - 'subprocess' : decode in a throwaway child (Termux default) so a native
                       decoder SIGILL can't take the whole packer down.
      - 'inprocess'  : decode directly (desktop default)."""
    mode = _decode_mode()
    if mode == "subprocess":
        return _decode_texture_via_subprocess(bundle_path, log)
    return _extract_body_texture_core(bundle_path, log=log, allow_decode=(mode != "off"))


def _extract_body_texture_core(bundle_path: str, log=None, allow_decode=True):
    """Find a body Texture2D and (when allow_decode) return (name, png_bytes).

    Tries hard so a real preview is produced when any texture exists:
      1) exact 'chXXXX_coXXXX_body' texture,
      2) any texture whose name contains 'body',
      3) the largest decodable texture.
    Crunched/compressed formats are decoded (not skipped). A `log` callback, when
    given, explains exactly why a placeholder ends up being used.

    WARNING: when allow_decode is True this touches the native texture decoders,
    which can hard-crash (SIGILL) on some Termux builds - run it in a child
    process there (see _decode_texture_via_subprocess)."""
    def _log(msg):
        if log:
            log(msg)

    if UnityPy is None:
        _log("  ⚠️ thumbnail: UnityPy not available"); return None, None
    try:
        env = UnityPy.load(bundle_path)
    except Exception as e:
        _log(f"  ⚠️ thumbnail: could not open bundle ({e})"); return None, None

    body_pat = re.compile(r"ch\d{4}_co\d{4}_body", re.IGNORECASE)
    # The base color/diffuse body texture is named '...body'. The same bundle also
    # ships auxiliary maps that share the 'body' name (rim light, normal, mask,
    # emission, ...) - those must NOT win the preview. Match them so we can skip.
    aux_pat = re.compile(
        r"(rim|nrm|normal|mask|msk|emi|emiss|metal|mtl|smooth|gloss|spec|_ao\b|occl|"
        r"sss|thick|alpha|_uv|toon|ramp|shadow|highlight|\bhi_|_hi\b)", re.IGNORECASE)
    exact_body_pat = re.compile(r"ch\d{4}_co\d{4}_body$", re.IGNORECASE)
    textures = []
    for obj in env.objects:
        if getattr(obj.type, "name", "") != "Texture2D":
            continue
        try:
            data = obj.read()
        except Exception:
            continue
        name = getattr(data, "m_Name", None) or getattr(data, "name", "") or ""
        textures.append((name, data))

    if not textures:
        _log("  ⚠️ thumbnail: no Texture2D in this bundle (the texture is probably "
             "in a separate bundle) - using a placeholder")
        return None, None

    # Decoding disabled (PACKER_DECODE_THUMBNAILS=0): don't touch the image data,
    # just hand back a texture name for the character ID and let the caller use a
    # name thumbnail.
    if not allow_decode:
        name_for_id = next((n for (n, _) in textures if re.search(r"ch\d{4}", n or "")), None)
        _log("  ℹ️ thumbnail: texture decode disabled (PACKER_DECODE_THUMBNAILS=0) "
             "- using a name thumbnail.")
        return name_for_id, None

    # astc-encoder-py imports archspec on the first decode; make it tolerate
    # Termux's platform.system() == "Android" before we touch any image data.
    _patch_platform_for_decode()

    def decode(name, data):
        try:
            img = getattr(data, "image", None)
        except Exception as e:
            _log(f"  ⚠️ thumbnail: texture '{name}' failed to decode ({e})")
            return None
        if not img:
            return None
        try:
            bio = io.BytesIO(); img.save(bio, format="PNG"); return bio.getvalue()
        except Exception as e:
            _log(f"  ⚠️ thumbnail: texture '{name}' could not be saved ({e})")
            return None

    def area(data):
        try:
            return int(getattr(data, "m_Width", 0) or 0) * int(getattr(data, "m_Height", 0) or 0)
        except Exception:
            return 0

    def is_aux(n):
        return bool(aux_pat.search(n or ""))

    # Prefer the plain body base color, biggest first, and only fall back to
    # auxiliary maps (rim/normal/...) as a last resort:
    #   1) exact 'chXXXX_coXXXX_body' (no rim/aux suffix)
    #   2) any 'chXXXX_coXXXX_body...' that isn't an auxiliary map
    #   3) any texture whose name contains 'body' and isn't auxiliary
    #   4) largest non-auxiliary texture
    #   5) largest texture (last resort - may be a rim/mask map)
    by_area = sorted(textures, key=lambda t: area(t[1]), reverse=True)
    tiers = [
        ([t for t in by_area if exact_body_pat.search(t[0] or "") and not is_aux(t[0])], "body texture"),
        ([t for t in by_area if body_pat.search(t[0] or "") and not is_aux(t[0])], "body texture"),
        ([t for t in by_area if "body" in (t[0] or "").lower() and not is_aux(t[0])], "name contains 'body'"),
        ([t for t in by_area if not is_aux(t[0])], "largest non-rim texture"),
        (by_area, "largest texture (no plain body texture found)"),
    ]
    tried = set()
    for tier, note in tiers:
        for n, d in tier:
            if id(d) in tried:
                continue
            tried.add(id(d))
            png = decode(n, d)
            if png:
                _log(f"  ℹ️ thumbnail: used {note} '{n}'")
                return n, png

    _log("  ⚠️ thumbnail: textures present but none could be decoded "
         "(unsupported compression) - using a placeholder")
    # Even if the image can't be decoded, hand back a texture name so the
    # character ID can still be read from it (e.g. 'ch0004_co0033_body' -> 4).
    name_for_id = next((n for (n, _) in textures if re.search(r"ch\d{4}", n or "")), None)
    return name_for_id, None


# A unique marker so the parent can pick the result line out of the child's
# stdout even if UnityPy/Pillow print their own noise around it.
_DECODE_RESULT_MARKER = b"__PACKER_DECODE_RESULT__"


def _decode_worker_main(bundle_path, out_png):
    """Child-process entry: decode the body texture and report back.

    Writes the PNG to out_png (if any) and prints one marker line carrying the
    base64 texture name and a 0/1 'png written' flag. Kept tiny so that if a
    native decoder hard-crashes (SIGILL) only this process dies."""
    name = png = None
    try:
        name, png = _extract_body_texture_core(bundle_path, log=None, allow_decode=True)
    except Exception:
        name, png = None, None
    wrote = False
    if png:
        try:
            with open(out_png, "wb") as f:
                f.write(png)
            wrote = True
        except Exception:
            wrote = False
    b64 = base64.b64encode((name or "").encode("utf-8"))
    sys.stdout.buffer.write(_DECODE_RESULT_MARKER + b"\t" + b64 + b"\t" + (b"1" if wrote else b"0") + b"\n")
    sys.stdout.buffer.flush()
    return 0


def _decode_texture_via_subprocess(bundle_path, log=None):
    """Decode the body texture in a throwaway child process.

    A native-decoder SIGILL ("Illegal instruction") then only kills the child;
    we read the texture name (for the character ID) from its stdout and fall back
    to a name thumbnail. Returns (name_or_None, png_bytes_or_None)."""
    def _log(msg):
        if log:
            log(msg)

    if UnityPy is None:
        _log("  ⚠️ thumbnail: UnityPy not available"); return None, None

    fd, out_png = tempfile.mkstemp(prefix="packer_thumb_", suffix=".png")
    os.close(fd)
    try:
        cmd = [sys.executable, _THIS_FILE, "--decode-worker", bundle_path, out_png]
        try:
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180)
        except subprocess.TimeoutExpired:
            _log("  ⚠️ thumbnail: texture decode timed out - using a name thumbnail.")
            return None, None
        except Exception as e:
            _log(f"  ⚠️ thumbnail: could not start decode worker ({e}) - using a name thumbnail.")
            return None, None

        name, png_flag = None, False
        for line in proc.stdout.splitlines():
            if line.startswith(_DECODE_RESULT_MARKER):
                parts = line.split(b"\t")
                if len(parts) >= 3:
                    try:
                        name = base64.b64decode(parts[1]).decode("utf-8", "replace") or None
                    except Exception:
                        name = None
                    png_flag = parts[2].strip() == b"1"

        if proc.returncode != 0 and not png_flag:
            if proc.returncode < 0:
                # negative == killed by a signal (e.g. -4 SIGILL, -11 SIGSEGV)
                _log(f"  ⚠️ thumbnail: the native texture decoder crashed (signal "
                     f"{-proc.returncode}) on this device - using a name thumbnail. "
                     f"Try rebuilding it from source:  pip install --force-reinstall "
                     f"--no-binary :all: astc-encoder-py texture2ddecoder etcpak")
            else:
                tail = proc.stderr.decode("utf-8", "replace").strip().splitlines()
                extra = f" ({tail[-1]})" if tail else ""
                _log(f"  ⚠️ thumbnail: decode worker failed{extra} - using a name thumbnail.")
            return name, None

        png = None
        if png_flag:
            try:
                with open(out_png, "rb") as f:
                    png = f.read() or None
            except Exception:
                png = None
        if not png:
            _log("  ℹ️ thumbnail: no decodable body texture in this bundle - using a name thumbnail.")
        return name, png
    finally:
        try:
            os.remove(out_png)
        except OSError:
            pass


def extract_chara_id_from_texture_name(tex_name: str):
    if not tex_name:
        return None
    m = re.search(r"ch(\d{4})_", tex_name)
    if m:
        return int(m.group(1))
    return None

def extract_chara_id_from_filename(filename: str):
    if not filename:
        return None
    m = re.match(r"^(\d+)", filename)          # leading id, e.g. "209rina...", "204suit"
    if m:
        try:
            return int(m.group(1))
        except Exception:
            pass
    m = re.search(r"ch(\d{4})", filename.lower())   # SIFAS style "ch0001_body...", "ch0209..."
    if m:
        return int(m.group(1))
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


def _clean_costume_name(name):
    s = str(name or "").replace("_", " ").replace("[", " ").replace("]", " ")
    return " ".join(s.split()) or "Costume"


def make_name_thumbnail_png(name, size: int = 256, chara_id=None):
    """Generate a thumbnail that simply shows the costume name (used when the
    body texture can't be decoded, e.g. on Termux). PIL text rendering works
    fine on Termux - only the native texture *decoders* are the problem."""
    if PIL is None:
        return None
    from PIL import Image, ImageDraw, ImageFont

    text = _clean_costume_name(name)
    img = Image.new("RGB", (size, size), (60, 63, 75))
    draw = ImageDraw.Draw(img)

    def get_font(px):
        px = max(10, int(px))
        try:
            return ImageFont.load_default(size=px)   # Pillow >= 10.1: scalable
        except TypeError:
            return ImageFont.load_default()          # older Pillow: tiny bitmap

    def text_w(s, font):
        try:
            return draw.textlength(s, font=font)
        except Exception:
            try:
                return font.getlength(s)
            except Exception:
                return len(s) * 6

    def line_h(font, px):
        try:
            asc, desc = font.getmetrics()
            return asc + desc + 2
        except Exception:
            return px + 4

    def wrap(words, font, maxw):
        lines, cur = [], ""
        for w in words:
            trial = (cur + " " + w).strip()
            if not cur or text_w(trial, font) <= maxw:
                cur = trial
            else:
                lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        return lines

    margin = max(8, size // 12)
    maxw = size - 2 * margin
    words = text.split()

    chosen = None
    for px in (size // 7, size // 8, size // 10, size // 12, size // 14, size // 16, 10):
        font = get_font(px)
        lines = wrap(words, font, maxw)
        lh = line_h(font, px)
        if lh * len(lines) <= size - 2 * margin and all(text_w(ln, font) <= maxw for ln in lines):
            chosen = (font, lines, lh)
            break
    if chosen is None:
        font = get_font(10)
        chosen = (font, wrap(words, font, maxw), line_h(font, 10))
    font, lines, lh = chosen

    y = (size - lh * len(lines)) // 2
    for ln in lines:
        x = (size - text_w(ln, font)) // 2
        try:
            draw.text((x + 1, y + 1), ln, fill=(0, 0, 0), font=font)   # shadow
        except Exception:
            pass
        draw.text((x, y), ln, fill=(245, 245, 245), font=font)
        y += lh

    if chara_id:
        bf = get_font(max(10, size // 16))
        try:
            draw.text((margin, size - margin - line_h(bf, size // 16)),
                      f"ID {chara_id}", fill=(230, 230, 230), font=bf)
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
def pack_safe_stem(stem):
    """Lowercase, ASCII-alphanumeric-only stem.

    costume_addon_installer renames each packed file to '<crc32hex><stem>' and
    rejects it unless that whole string is .isalnum() and .islower(). The crc32
    prefix is already lowercase hex, so the stem must be lowercase a-z / 0-9 with
    NO underscores, spaces, hyphens or capitals. Leading digits (the character-id
    prefix like '305') are preserved."""
    s = "".join(c for c in str(stem).lower() if ("a" <= c <= "z") or ("0" <= c <= "9"))
    return s or "costume"


def safe_arc_name(original_filename):
    """Zip arcname / costume_file value with a sanitized stem. The extension is
    stripped by the installer (only the stem becomes the asset-bundle name), so we
    just keep a harmless, non-numeric '.unity' extension."""
    base = os.path.basename(str(original_filename))
    stem, ext = os.path.splitext(base)
    if not ext or ext[1:].isdigit():   # never leave a numeric ext (installer reads it as chara_id)
        ext = ".unity"
    return pack_safe_stem(stem) + ext


def generate_modinstall_txt(display_name: str, costume_file_name_with_ext: str, thumbnail_name: str, chara_id: int, unmask_filename: str = None,
                            ios_costume_filename: str = None, ios_unmask_filename: str = None):
    """modinstall.txt 내용을 생성한다.

    ios_costume_filename이 주어지면 듀얼 플랫폼(합본) 설정을 추가한다.
    - costume_file        : 안드로이드 번들 (구버전 인스톨러는 이것만 읽어 안드로이드용으로 설치)
    - costume_file_ios    : iOS 번들 (신버전 인스톨러만 사용; 구버전은 무해하게 무시)
    """
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

    lines.append('')
    if ios_costume_filename:
        lines.append('# dual platform package (new installer registers iOS side too;')
        lines.append('# old installer safely ignores these and installs the android files above)')
        lines.append(f'costume_file_ios = "{ios_costume_filename}"')
        if chara_id == 209 and ios_unmask_filename:
            lines.append(f'rina_unmask_costume_file_ios = "{ios_unmask_filename}"')
        else:
            lines.append('rina_unmask_costume_file_ios = ""')
    else:
        # 배치 설치 시 이전 애드온의 듀얼 설정이 이월되지 않도록 항상 초기화
        lines.append('costume_file_ios = ""')
        lines.append('rina_unmask_costume_file_ios = ""')

    return "\n".join(lines)

def create_zip_package(output_zip_path: str, masked_bundle_path: str, thumbnail_bytes: bytes, thumbnail_name: str, modinstall_txt: str, unmasked_bundle_path: str = None,
                       masked_arcname: str = None, unmasked_arcname: str = None):
    os.makedirs(os.path.dirname(output_zip_path), exist_ok=True)
    with zipfile.ZipFile(output_zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        # masked (main) file - stored under an installer-safe name
        zf.write(masked_bundle_path, masked_arcname or os.path.basename(masked_bundle_path))

        # unmasked (paired) file if it exists
        if unmasked_bundle_path and os.path.isfile(unmasked_bundle_path):
            zf.write(unmasked_bundle_path, unmasked_arcname or os.path.basename(unmasked_bundle_path))

        # thumbnail and modinstall
        zf.writestr(thumbnail_name, thumbnail_bytes)
        zf.writestr("modinstall.txt", modinstall_txt.encode("utf-8"))
    return True


# ============================================================
# Headless packaging (used by the Termux text menu). These mirror the GUI's
# process_single_file / process_pair / process_files, but take plain params and
# a `log` callback instead of touching Tk widgets.
# ============================================================
def normalize_rina_key(filename: str):
    """'209rinamasked...' / '209rinaunmasked...' -> 'rina...' for pairing."""
    s = re.sub(r"^\d+", "", filename, count=1).lower()
    if s.startswith("rinamasked"):
        return s.replace("rinamasked", "rina", 1)
    if s.startswith("rinaunmasked"):
        return s.replace("rinaunmasked", "rina", 1)
    return s


def pack_single_bundle(bundle_path, out_dir, *, auto_chara_id=True, manual_chara_id=0,
                       thumbnail_size=256, append_suffix=True, rina_unmasked_map=None,
                       platform=None, ask_chara_id=None, log=print):
    """Package one bundle into a zip in out_dir. Returns the zip path or None."""
    rina_unmasked_map = rina_unmasked_map or {}
    bn_with_ext = os.path.basename(bundle_path)
    bn_no_ext = os.path.splitext(bn_with_ext)[0]

    if platform is None:
        platform = detect_bundle_platform(bundle_path)
    if platform is None and append_suffix:
        log(f"  ❓ Platform unknown for '{bn_with_ext}' - zip name will have no platform suffix")

    tex_name, tex_png_bytes = extract_body_texture_with_unitypy(bundle_path, log=log)

    if auto_chara_id:
        cid = (extract_chara_id_from_texture_name(tex_name)
               or extract_chara_id_from_filename(bn_no_ext))
        if cid is None:
            # Don't silently fall back to 209 (that triggers the installer's Rina
            # path and crashes without an unmasked model). Ask, or use the manual id.
            cid = ask_chara_id(bn_with_ext) if ask_chara_id else manual_chara_id
    else:
        cid = manual_chara_id
    if bn_no_ext.lower().startswith("209rinamasked") and cid != 209:
        log(f"  ⚠️ Overriding chara_id to 209 for Rina file '{bn_with_ext}'")
        cid = 209
    log(f"  🎯 Chara ID: {cid}")

    thumb_bytes = (make_thumbnail_png(tex_png_bytes, thumbnail_size) if tex_png_bytes
                   else make_name_thumbnail_png(bn_no_ext, thumbnail_size, cid))
    if not thumb_bytes:
        log("  ❌ Thumbnail creation failed."); return None
    thumb_name = "im" + pack_safe_stem(bn_no_ext) + ".png"

    unmasked_bundle_path = unmasked_filename = None
    if cid == 209 and bn_no_ext.lower().startswith("209rinamasked"):
        key = normalize_rina_key(bn_no_ext.lower())
        if key in rina_unmasked_map:
            unmasked_bundle_path = rina_unmasked_map[key]
            unmasked_filename = os.path.basename(unmasked_bundle_path)
            log(f"  🎭 Paired with '{unmasked_filename}'")

    if cid == 209 and not unmasked_bundle_path:
        log("  ❌ chara_id is 209 (Rina), which REQUIRES an unmasked model "
            "('209rinaunmasked...') - none was found.")
        log("     Add the unmasked file next to this one, or set the correct "
            "character ID. Skipping (the installer would crash otherwise).")
        return None

    safe_costume = safe_arc_name(bn_with_ext)
    safe_unmask = safe_arc_name(unmasked_filename) if unmasked_filename else None
    modinstall = generate_modinstall_txt(bn_no_ext, safe_costume, thumb_name, cid, safe_unmask)
    zip_base = compute_zip_basename(bn_no_ext, platform, append_suffix)
    out_zip = os.path.join(out_dir, f"{zip_base}.zip")
    if create_zip_package(out_zip, bundle_path, thumb_bytes, thumb_name, modinstall,
                          unmasked_bundle_path, masked_arcname=safe_costume,
                          unmasked_arcname=safe_unmask):
        log(f"  💾 Created: {os.path.basename(out_zip)}")
        return out_zip
    return None


def pack_pair_bundles(pair_key, android_path, ios_path, out_dir, *, auto_chara_id=True,
                      manual_chara_id=0, thumbnail_size=256, rina_unmasked_map=None,
                      ask_chara_id=None, log=print):
    """Package an Android+iOS pair into one combined zip. Returns True/False."""
    rina_unmasked_map = rina_unmasked_map or {}
    and_name = os.path.basename(android_path)
    ios_name = os.path.basename(ios_path)
    and_no_ext = os.path.splitext(and_name)[0]

    tex_name, tex_png_bytes = extract_body_texture_with_unitypy(android_path, log=log)
    if not tex_png_bytes:
        tex_name, tex_png_bytes = extract_body_texture_with_unitypy(ios_path, log=log)

    if auto_chara_id:
        cid = (extract_chara_id_from_texture_name(tex_name)
               or extract_chara_id_from_filename(and_no_ext)
               or extract_chara_id_from_filename(os.path.splitext(ios_name)[0]))
        if cid is None:
            cid = ask_chara_id(and_name) if ask_chara_id else manual_chara_id
    else:
        cid = manual_chara_id
    if (and_no_ext.lower().startswith("209rinamasked")
            or os.path.splitext(ios_name)[0].lower().startswith("209rinamasked")) and cid != 209:
        cid = 209
    log(f"  🎯 Chara ID: {cid}")

    thumb_bytes = (make_thumbnail_png(tex_png_bytes, thumbnail_size) if tex_png_bytes
                   else make_name_thumbnail_png(pair_key, thumbnail_size, cid))
    if not thumb_bytes:
        log("  ❌ Thumbnail creation failed."); return False
    thumb_name = "im" + pack_safe_stem(pair_key) + ".png"

    unmask_and_path = unmask_and_name = None
    unmask_ios_path = unmask_ios_name = None
    if cid == 209:
        key_and = normalize_rina_key(and_no_ext.lower())
        key_ios = normalize_rina_key(os.path.splitext(ios_name)[0].lower())
        if key_and in rina_unmasked_map:
            unmask_and_path = rina_unmasked_map[key_and]; unmask_and_name = os.path.basename(unmask_and_path)
            log(f"  🎭 Paired android with '{unmask_and_name}'")
        if key_ios in rina_unmasked_map:
            unmask_ios_path = rina_unmasked_map[key_ios]; unmask_ios_name = os.path.basename(unmask_ios_path)
            log(f"  🎭 Paired ios with '{unmask_ios_name}'")

    if cid == 209 and not unmask_and_path:
        log("  ❌ chara_id is 209 (Rina), which REQUIRES an unmasked model "
            "('209rinaunmasked...') - none was found.")
        log("     Add the unmasked file, or set the correct character ID. "
            "Skipping (the installer would crash otherwise).")
        return False

    safe_and = safe_arc_name(and_name)
    safe_ios = safe_arc_name(ios_name)
    safe_unmask_and = safe_arc_name(unmask_and_name) if unmask_and_name else None
    safe_unmask_ios = safe_arc_name(unmask_ios_name) if unmask_ios_name else None
    modinstall = generate_modinstall_txt(pair_key, safe_and, thumb_name, cid, safe_unmask_and,
                                         ios_costume_filename=safe_ios, ios_unmask_filename=safe_unmask_ios)
    combined = os.path.join(out_dir, f"{pair_key}_apk_ios.zip")
    os.makedirs(os.path.dirname(combined), exist_ok=True)
    with zipfile.ZipFile(combined, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.write(android_path, safe_and)
        zf.write(ios_path, safe_ios)
        if unmask_and_path and os.path.isfile(unmask_and_path):
            zf.write(unmask_and_path, safe_unmask_and)
        if unmask_ios_path and os.path.isfile(unmask_ios_path):
            zf.write(unmask_ios_path, safe_unmask_ios)
        zf.writestr(thumb_name, thumb_bytes)
        zf.writestr("modinstall.txt", modinstall.encode("utf-8"))
    log(f"  💾 Created combined: {os.path.basename(combined)} (android={and_name}, ios={ios_name})")
    return True


def run_pack_jobs(files, out_dir, *, auto_chara_id=True, manual_chara_id=0,
                  thumbnail_size=256, append_suffix=True, combine_pairs=True,
                  ask_chara_id=None, log=print):
    """Pre-scan Rina unmasked helpers, detect platforms, build jobs (pairing
    android+ios), and package each into out_dir. Returns (success, fail)."""
    out_dir = os.path.expanduser(out_dir)
    os.makedirs(out_dir, exist_ok=True)

    rina_map = {}
    masked = []
    for p in files:
        bn = os.path.splitext(os.path.basename(p))[0].lower()
        if bn.startswith("209rinaunmasked"):
            rina_map[normalize_rina_key(bn)] = p
        else:
            masked.append(p)
    if rina_map:
        log(f"✅ Found {len(rina_map)} '209rinaunmasked' helper file(s).")

    log("🔎 Detecting bundle platforms (Android / iOS)...")
    platforms = {}
    for p in masked:
        plat = detect_bundle_platform(p)
        platforms[p] = plat
        icon = {'android': '🤖', 'ios': '🍎'}.get(plat, '❓')
        log(f"  {icon} {os.path.basename(p)}: {plat or 'unknown'}")

    jobs = build_pack_jobs(masked, platforms, combine_pairs)
    pair_count = sum(1 for j in jobs if j[0] == 'pair')
    if combine_pairs:
        if pair_count:
            log(f"🔗 Matched {pair_count} Android+iOS pair(s) -> combined zip(s)")
        else:
            log("🟡 No Android+iOS pairs matched (files packed individually).")

    success = fail = 0
    total = len(jobs)
    for i, job in enumerate(jobs, 1):
        try:
            if job[0] == 'pair':
                _, key, ap, ip = job
                log(f"\n📦 [{i}/{total}] pair: {os.path.basename(ap)} + {os.path.basename(ip)}")
                ok = pack_pair_bundles(key, ap, ip, out_dir, auto_chara_id=auto_chara_id,
                                       manual_chara_id=manual_chara_id, thumbnail_size=thumbnail_size,
                                       rina_unmasked_map=rina_map, ask_chara_id=ask_chara_id, log=log)
            else:
                bp = job[1]
                log(f"\n📦 [{i}/{total}] {os.path.basename(bp)}")
                ok = bool(pack_single_bundle(bp, out_dir, auto_chara_id=auto_chara_id,
                                             manual_chara_id=manual_chara_id, thumbnail_size=thumbnail_size,
                                             append_suffix=append_suffix, rina_unmasked_map=rina_map,
                                             ask_chara_id=ask_chara_id,
                                             platform=platforms.get(bp), log=log))
            if ok:
                success += 1
            else:
                fail += 1
        except Exception as e:
            fail += 1
            log(f"  ❌ ERROR: {e}")
    log(f"\n🎉 Done. ✅ Successful: {success}  ❌ Failed: {fail}   (output: {out_dir})")
    return success, fail


# -------- Library scan helpers (modded source) --------
def is_unity_bundle(path):
    try:
        with open(path, "rb") as f:
            return f.read(7) == b"UnityFS"
    except Exception:
        return False


def find_asset_bundles(root):
    """Recursively list UnityFS asset bundles under root (sorted)."""
    root = os.path.expanduser(str(root))
    if not os.path.isdir(root):
        return []
    out = []
    for dp, _, files in os.walk(root):
        for fn in files:
            p = os.path.join(dp, fn)
            if is_unity_bundle(p):
                out.append(p)
    return sorted(out)


def build_thumbnail_for_bundle(bundle_path, size=256, log=None):
    """Return (png_bytes, label) for a preview thumbnail of one bundle.

    Decodes the body base-color texture (crash-safe via extract_body_texture_with_unitypy)
    and falls back to a name thumbnail when nothing decodes. Shared by the web GUI,
    the desktop GUI preview, and any caller that just wants a picture for a bundle."""
    bn_no_ext = os.path.splitext(os.path.basename(bundle_path))[0]
    tex_name, tex_png = extract_body_texture_with_unitypy(bundle_path, log=log)
    cid = (extract_chara_id_from_texture_name(tex_name)
           or extract_chara_id_from_filename(bn_no_ext))
    if tex_png:
        png = make_thumbnail_png(tex_png, size)
        if png:
            return png, (tex_name or bn_no_ext)
    return make_name_thumbnail_png(bn_no_ext, size, cid), (tex_name or bn_no_ext)


# -------- Text menu (Termux / headless): modded -> suit --------
def _ask(prompt, default=""):
    s = input(f"{prompt} [{default}]: ").strip() if default != "" else input(f"{prompt}: ").strip()
    return s if s else default


def _ask_yesno(prompt, default=True):
    d = "Y/n" if default else "y/N"
    s = input(f"{prompt} [{d}]: ").strip().lower()
    if s == "":
        return default
    return s in ("y", "yes")


def _ask_int(prompt):
    """Prompt until the user enters a non-negative integer (no risky default)."""
    while True:
        s = input(f"{prompt}: ").strip()
        if s.isdigit():
            return int(s)
        print("   Please enter a number (digits only).")


def _parse_multi_select(s, n):
    """'3' / '1,4-8' / 'all' -> sorted 0-based indices in 1..n."""
    s = (s or "").strip().lower()
    if s in ("all", "*"):
        return list(range(n))
    out = set()
    for part in s.replace(" ", "").split(","):
        if not part:
            continue
        if "-" in part:
            a, _, b = part.partition("-")
            try:
                a, b = int(a), int(b)
            except ValueError:
                continue
            for k in range(min(a, b), max(a, b) + 1):
                if 1 <= k <= n:
                    out.add(k - 1)
        else:
            try:
                k = int(part)
            except ValueError:
                continue
            if 1 <= k <= n:
                out.add(k - 1)
    return sorted(out)


def run_menu():
    """Termux/headless: pick bundles from sukusta/modded, pack -> sukusta/suit."""
    try:
        import readline  # noqa: F401  (arrow-key editing / history)
    except Exception:
        pass

    if UnityPy is None or PIL is None:
        print("⚠️  UnityPy/Pillow are required for packaging.")
        print(f"   UnityPy: {'OK' if UnityPy else 'MISSING'}   Pillow: {'OK' if PIL else 'MISSING'}")
        print("   Install with:  pip install UnityPy Pillow")
        return

    modded = default_sukusta_dir("modded")
    suit = default_sukusta_dir("suit")
    print()
    print("==========================================")
    print("     Unity Costume Mod Packer")
    print("     (modded -> suit, text mode)")
    print("==========================================")
    print(f"  source (modded): {modded}")
    print(f"  output (suit)  : {suit}")

    if _ask_yesno("\nOpen the graphical Web GUI in a browser instead? "
                  "(pick bundles visually, with thumbnails)", default=False):
        return run_web()

    print(f"\nScanning {modded} ...")
    bundles = find_asset_bundles(modded)
    if not bundles:
        print("No unity asset bundles (UnityFS files) found in modded.")
        print("Put your modded .unity bundles there first, or set SUKUSTA_DIR.")
        return
    for i, b in enumerate(bundles, 1):
        try:
            rel = os.path.relpath(b, modded)
        except Exception:
            rel = os.path.basename(b)
        print(f"  {i:3d}) {rel}")
    chosen = _parse_multi_select(_ask("Select bundle(s)  (e.g. 3, 1,4-8, all)", "all"), len(bundles))
    if not chosen:
        print("Nothing selected."); return
    files = [bundles[i] for i in chosen]

    combine_pairs = _ask_yesno("Combine detected Android+iOS pairs into one zip?", default=True)
    append_suffix = _ask_yesno("Append platform suffix (_apk / _ios) to zip names?", default=True)
    auto_cid = _ask_yesno("Auto-detect character ID from each file?", default=True)
    manual_cid = 0
    if not auto_cid:
        manual_cid = _ask_int("Character ID to use for ALL selected files (e.g. 1, 105, 209)")

    def _ask_cid_for(fname):
        print(f"\n⚠️  Could not auto-detect the character ID for: {fname}")
        return _ask_int("   Enter character ID "
                        "(1-9 = mu's, 101-109 = Aqours, 201-212 = Nijigasaki; 209 = Rina)")

    print(f"\nPackaging {len(files)} bundle(s) -> {suit}\n")
    run_pack_jobs(files, suit, auto_chara_id=auto_cid, manual_chara_id=manual_cid,
                  thumbnail_size=256, append_suffix=append_suffix, combine_pairs=combine_pairs,
                  ask_chara_id=(_ask_cid_for if auto_cid else None), log=print)


# ============================================================
# Web GUI (Termux-friendly): a tiny stdlib-only HTTP server you open in a phone
# browser. tkinter isn't available on Termux, so this is the graphical option
# there. It reuses the same packing functions as the text menu / desktop GUI.
# ============================================================
_WEB_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Unity Costume Mod Packer</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin:0; font-family: system-ui, sans-serif; background:#1e1f26; color:#e7e7ea; }
  header { padding:12px 16px; background:#2a2c37; position:sticky; top:0; z-index:5;
           box-shadow:0 2px 6px rgba(0,0,0,.4); }
  h1 { font-size:17px; margin:0 0 2px; }
  .paths { font-size:11px; color:#9aa; word-break:break-all; }
  main { padding:12px 16px 96px; max-width:760px; margin:0 auto; }
  .opts { display:flex; flex-wrap:wrap; gap:10px 18px; align-items:center;
          background:#262833; padding:12px; border-radius:10px; margin-bottom:12px; }
  .opts label { font-size:13px; display:flex; gap:6px; align-items:center; }
  .opts input[type=number] { width:72px; background:#1b1c22; color:#e7e7ea;
          border:1px solid #444; border-radius:6px; padding:3px 6px; }
  .toolbar { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:10px; }
  button { background:#4a6cf7; color:#fff; border:0; border-radius:8px;
           padding:9px 14px; font-size:14px; cursor:pointer; }
  button.sec { background:#3a3d4a; }
  button:disabled { opacity:.5; cursor:default; }
  ul.bundles { list-style:none; padding:0; margin:0; display:grid;
           grid-template-columns:repeat(auto-fill,minmax(150px,1fr)); gap:10px; }
  li.card { background:#262833; border-radius:10px; padding:8px; position:relative;
           border:2px solid transparent; }
  li.card.sel { border-color:#4a6cf7; }
  li.card img { width:100%; aspect-ratio:1/1; object-fit:contain; background:#15161b;
           border-radius:6px; display:block; }
  .name { font-size:11px; margin-top:6px; word-break:break-all; line-height:1.3; }
  .badge { position:absolute; top:10px; right:10px; font-size:11px; background:#000a;
           padding:1px 6px; border-radius:8px; }
  .row-cb { position:absolute; top:10px; left:10px; transform:scale(1.3); }
  #log { white-space:pre-wrap; font-family:ui-monospace,monospace; font-size:12px;
         background:#15161b; border-radius:8px; padding:10px; margin-top:12px;
         max-height:40vh; overflow:auto; }
  .bar { position:fixed; left:0; right:0; bottom:0; background:#2a2c37; padding:10px 16px;
         display:flex; gap:10px; align-items:center; box-shadow:0 -2px 6px rgba(0,0,0,.4); }
  .bar .grow { flex:1; font-size:13px; color:#9aa; }
</style>
</head>
<body>
<header>
  <h1>🎽 Unity Costume Mod Packer</h1>
  <div class="paths" id="paths">loading…</div>
</header>
<main>
  <div class="opts">
    <label><input type="checkbox" id="combine" checked> Combine APK+iOS pairs</label>
    <label><input type="checkbox" id="suffix" checked> Append _apk/_ios suffix</label>
    <label><input type="checkbox" id="auto" checked> Auto chara ID</label>
    <label>Manual ID <input type="number" id="cid" value="0" min="0" max="999"></label>
    <label>Thumb px <input type="number" id="size" value="256" min="64" max="512" step="16"></label>
  </div>
  <div class="toolbar">
    <button class="sec" onclick="loadBundles()">🔄 Refresh</button>
    <button class="sec" onclick="selectAll(true)">Select all</button>
    <button class="sec" onclick="selectAll(false)">Clear</button>
  </div>
  <ul class="bundles" id="list"></ul>
  <div id="log" hidden></div>
</main>
<div class="bar">
  <span class="grow" id="count">0 selected</span>
  <button id="packbtn" onclick="pack()">🚀 Pack selected</button>
</div>
<script>
let BUNDLES = [];
const sel = new Set();
const $ = id => document.getElementById(id);

async function loadConfig(){
  const c = await (await fetch('api/config')).json();
  $('paths').textContent = 'modded: ' + c.modded + '   →   suit: ' + c.suit;
}
async function loadBundles(){
  $('list').innerHTML = '<li>scanning…</li>';
  const data = await (await fetch('api/bundles')).json();
  BUNDLES = data.bundles; sel.clear();
  render(); updateCount();
}
function render(){
  const ul = $('list'); ul.innerHTML = '';
  if(!BUNDLES.length){ ul.innerHTML = '<li>No bundles in the modded folder.</li>'; return; }
  BUNDLES.forEach((b,i) => {
    const li = document.createElement('li'); li.className = 'card' + (sel.has(b.path)?' sel':'');
    const icon = b.platform==='android'?'🤖':b.platform==='ios'?'🍎':'❓';
    li.innerHTML =
      '<input class="row-cb" type="checkbox" '+(sel.has(b.path)?'checked':'')+'>' +
      '<span class="badge">'+icon+'</span>' +
      '<img loading="lazy" src="api/thumb?size='+($("size").value||256)+'&path='+encodeURIComponent(b.path)+'">' +
      '<div class="name">'+b.rel+'</div>';
    const toggle = () => { if(sel.has(b.path)) sel.delete(b.path); else sel.add(b.path);
                           li.classList.toggle('sel'); li.querySelector('.row-cb').checked=sel.has(b.path); updateCount(); };
    li.querySelector('img').onclick = toggle;
    li.querySelector('.name').onclick = toggle;
    li.querySelector('.row-cb').onchange = toggle;
    ul.appendChild(li);
  });
}
function selectAll(on){ sel.clear(); if(on) BUNDLES.forEach(b=>sel.add(b.path)); render(); updateCount(); }
function updateCount(){ $('count').textContent = sel.size + ' selected'; }
async function pack(){
  if(!sel.size){ alert('Select at least one bundle.'); return; }
  const btn = $('packbtn'); btn.disabled = true; btn.textContent = '⏳ Packing…';
  const log = $('log'); log.hidden = false; log.textContent = 'Packing '+sel.size+' bundle(s)…\n';
  try {
    const res = await fetch('api/pack', { method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({
        files:[...sel], combine_pairs:$('combine').checked, append_suffix:$('suffix').checked,
        auto_chara_id:$('auto').checked, manual_chara_id:parseInt($('cid').value||'0'),
        thumbnail_size:parseInt($('size').value||'256') }) });
    const data = await res.json();
    log.textContent = (data.log||[]).join('\n') +
      '\n\n🎉 Done. ✅ '+data.success+'  ❌ '+data.fail;
    log.scrollTop = log.scrollHeight;
  } catch(e){ log.textContent += '\n❌ Error: '+e; }
  btn.disabled = false; btn.textContent = '🚀 Pack selected';
}
loadConfig(); loadBundles();
</script>
</body>
</html>
"""


def _path_within(root, p):
    """True if p resolves to a location inside root (blocks path-traversal)."""
    try:
        rr = os.path.realpath(os.path.expanduser(root))
        rp = os.path.realpath(p)
        return rp == rr or os.path.commonpath([rp, rr]) == rr
    except Exception:
        return False


def run_web(host="127.0.0.1", port=8000, open_browser=False):
    """Serve the browser GUI (stdlib only). modded -> suit, same as the text menu."""
    import json
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import urlparse, parse_qs

    if UnityPy is None or PIL is None:
        print("⚠️  UnityPy/Pillow are required for the web GUI.")
        print(f"   UnityPy: {'OK' if UnityPy else 'MISSING'}   Pillow: {'OK' if PIL else 'MISSING'}")
        return

    modded = default_sukusta_dir("modded")
    suit = default_sukusta_dir("suit")
    os.makedirs(modded, exist_ok=True)
    thumb_cache = {}
    pack_lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass  # quiet

        def _send(self, code, body, ctype="application/json; charset=utf-8"):
            if isinstance(body, str):
                body = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except BrokenPipeError:
                pass

        def _json(self, code, obj):
            self._send(code, json.dumps(obj), "application/json; charset=utf-8")

        def do_GET(self):
            u = urlparse(self.path)
            if u.path in ("/", "/index.html"):
                return self._send(200, _WEB_HTML, "text/html; charset=utf-8")
            if u.path == "/api/config":
                return self._json(200, {"modded": modded, "suit": suit})
            if u.path == "/api/bundles":
                bundles = []
                for p in find_asset_bundles(modded):
                    try:
                        rel = os.path.relpath(p, modded)
                    except Exception:
                        rel = os.path.basename(p)
                    bundles.append({"path": p, "rel": rel, "name": os.path.basename(p),
                                    "platform": detect_bundle_platform(p)})
                return self._json(200, {"modded": modded, "suit": suit, "bundles": bundles})
            if u.path == "/api/thumb":
                q = parse_qs(u.query)
                path = (q.get("path") or [""])[0]
                try:
                    size = max(64, min(512, int((q.get("size") or ["256"])[0])))
                except ValueError:
                    size = 256
                if not path or not _path_within(modded, path) or not os.path.isfile(path):
                    return self._send(404, b"not found", "text/plain")
                try:
                    key = (os.path.realpath(path), int(os.path.getmtime(path)), size)
                except OSError:
                    key = (path, 0, size)
                png = thumb_cache.get(key)
                if png is None:
                    png, _ = build_thumbnail_for_bundle(path, size=size, log=None)
                    png = png or b""
                    thumb_cache[key] = png
                if not png:
                    return self._send(404, b"no thumb", "text/plain")
                return self._send(200, png, "image/png")
            return self._send(404, b"not found", "text/plain")

        def do_POST(self):
            u = urlparse(self.path)
            if u.path != "/api/pack":
                return self._send(404, b"not found", "text/plain")
            try:
                length = int(self.headers.get("Content-Length") or 0)
                req = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            except Exception as e:
                return self._json(400, {"error": f"bad request: {e}"})

            files = [p for p in (req.get("files") or [])
                     if _path_within(modded, p) and os.path.isfile(p)]
            if not files:
                return self._json(400, {"error": "no valid files selected"})

            logs = []
            if not pack_lock.acquire(blocking=False):
                return self._json(409, {"error": "a packing job is already running"})
            try:
                os.makedirs(suit, exist_ok=True)
                success, fail = run_pack_jobs(
                    files, suit,
                    auto_chara_id=bool(req.get("auto_chara_id", True)),
                    manual_chara_id=int(req.get("manual_chara_id") or 0),
                    thumbnail_size=int(req.get("thumbnail_size") or 256),
                    append_suffix=bool(req.get("append_suffix", True)),
                    combine_pairs=bool(req.get("combine_pairs", True)),
                    ask_chara_id=None, log=logs.append)
            except Exception as e:
                logs.append(f"❌ ERROR: {e}")
                success, fail = 0, len(files)
            finally:
                pack_lock.release()
            return self._json(200, {"success": success, "fail": fail, "log": logs, "out": suit})

    httpd = ThreadingHTTPServer((host, port), Handler)
    actual_port = httpd.server_address[1]
    url = f"http://{host}:{actual_port}/"
    print("\n==========================================")
    print("     Unity Costume Mod Packer - Web GUI")
    print("==========================================")
    print(f"  source (modded): {modded}")
    print(f"  output (suit)  : {suit}")
    print(f"\n  ✅ Open this in your browser:\n     {url}")
    if host not in ("127.0.0.1", "localhost"):
        print("  ⚠️ Bound to a non-local address - anyone on your network can reach it.")
    print("\n  (Press Ctrl+C to stop the server.)\n")
    if open_browser:
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping web GUI.")
    finally:
        httpd.server_close()


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
        # macOS는 기본 폰트/위젯 패딩이 커서 같은 높이에 내용이 덜 들어간다.
        # 플랫폼별로 기본 크기를 다르게 주고, 작은 화면을 대비해 스크롤도 둔다.
        if sys.platform == "darwin":
            self.root.geometry("1000x820")
        else:
            self.root.geometry("1000x800")
        self.root.minsize(760, 480)
        self.root.resizable(True, True)
        
        self.bundle_files = []
        self.output_dir = tk.StringVar(value=default_sukusta_dir("suit"))
        self.thumbnail_size = tk.IntVar(value=256)
        self.chara_id = tk.IntVar(value=209) # Default for Rina
        self.auto_chara_id = tk.BooleanVar(value=True)
        self.batch_mode = tk.BooleanVar(value=True) # Default to batch
        self.output_to_bundle_location = tk.BooleanVar(value=True)
        self.append_platform_suffix = tk.BooleanVar(value=True)
        self.combine_pairs = tk.BooleanVar(value=True)
        self.is_processing = False
        self.current_file_index = 0
        self.total_files = 0
        
        self.rina_unmasked_map = {}
        self.bundle_platforms = {}
        
        self._i18n = []
        self.setup_ui()

    def _reg(self, widget, key, kind="text"):
        self._i18n.append((widget, key, kind)); return widget

    def _apply_i18n(self):
        self.root.title(_tr("Unity Asset Bundle Mod Packer"))
        for w, key, kind in self._i18n:
            try: w.configure(**{kind: _tr(key)})
            except Exception: pass

    def _change_language(self, code):
        _set_lang(code); self._apply_i18n()

    def setup_ui(self):
        # 창이 작아도 모든 위젯에 접근할 수 있도록 전체 폼을 스크롤 캔버스에 담는다.
        # (macOS에서 창 아래가 잘리던 문제 해결)
        outer = ttk.Frame(self.root)
        outer.grid(row=0, column=0, sticky="nsew")
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(0, weight=1)

        self.canvas = tk.Canvas(outer, highlightthickness=0)
        vscroll = ttk.Scrollbar(outer, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=vscroll.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        vscroll.grid(row=0, column=1, sticky="ns")

        main = ttk.Frame(self.canvas, padding=10)
        self._main_window = self.canvas.create_window((0, 0), window=main, anchor="nw")

        # 내용 크기가 바뀌면 스크롤 영역을 갱신하고, 캔버스 폭에 맞춰 내부 폭을 늘린다.
        def _on_main_configure(event):
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        main.bind("<Configure>", _on_main_configure)

        def _on_canvas_configure(event):
            self.canvas.itemconfigure(self._main_window, width=event.width)
        self.canvas.bind("<Configure>", _on_canvas_configure)

        # 마우스 휠 스크롤 (Windows/macOS는 <MouseWheel>, Linux는 Button-4/5)
        def _on_mousewheel(event):
            if event.num == 4:
                self.canvas.yview_scroll(-1, "units")
            elif event.num == 5:
                self.canvas.yview_scroll(1, "units")
            else:
                delta = event.delta
                # macOS는 delta가 작은 정수, Windows는 120 배수
                step = -1 * (delta if abs(delta) < 30 else delta // 120)
                self.canvas.yview_scroll(int(step), "units")

        def _bind_wheel(_=None):
            self.canvas.bind_all("<MouseWheel>", _on_mousewheel)
            self.canvas.bind_all("<Button-4>", _on_mousewheel)
            self.canvas.bind_all("<Button-5>", _on_mousewheel)

        def _unbind_wheel(_=None):
            self.canvas.unbind_all("<MouseWheel>")
            self.canvas.unbind_all("<Button-4>")
            self.canvas.unbind_all("<Button-5>")

        self.canvas.bind("<Enter>", _bind_wheel)
        self.canvas.bind("<Leave>", _unbind_wheel)

        title = _tr("Unity Asset Bundle Mod Packer (Rina Auto-Pair)")
        if UnityPy is None:
            title += _tr(" [UnityPy installation required]")
        self._reg(ttk.Label(main, text=title, font=("Arial", 16, "bold")), "Unity Asset Bundle Mod Packer (Rina Auto-Pair)").grid(row=0, column=0, columnspan=4, pady=(0, 20))
        
        st = ttk.Frame(main); st.grid(row=1, column=0, columnspan=4, sticky="w", pady=5)
        ttk.Label(st, text=f"UnityPy: {'OK' if UnityPy else 'Missing'}", foreground="green" if UnityPy else "red").grid(row=0, column=0, sticky="w", padx=(0,10))
        ttk.Label(st, text=f"Pillow: {'OK' if PIL else 'Missing'}", foreground="green" if PIL else "red").grid(row=0, column=1, sticky="w", padx=(0,10))
        if (UnityPy is None) or (PIL is None):
            self._reg(ttk.Button(st, text=_tr("Install required modules"), command=self.install_requirements), "Install required modules").grid(row=0, column=2, padx=10)

        # language picker (status row, right side)
        self._reg(ttk.Label(st, text=_tr("Language")), "Language").grid(row=0, column=3, sticky="e", padx=(20, 4))
        _names = [n for _c, n in _lang_opts()]
        _code_by_name = {n: c for c, n in _lang_opts()}
        _name_by_code = {c: n for c, n in _lang_opts()}
        self._lang_var = tk.StringVar(value=_name_by_code.get(_get_lang(), _names[0]))
        _lang_cb = ttk.Combobox(st, textvariable=self._lang_var, values=_names, state="readonly", width=10)
        _lang_cb.grid(row=0, column=4, sticky="e")
        _lang_cb.bind("<<ComboboxSelected>>", lambda e: self._change_language(_code_by_name[self._lang_var.get()]))

        mode = self._reg(ttk.LabelFrame(main, text=_tr("Processing Mode"), padding=10), "Processing Mode")
        mode.grid(row=2, column=0, columnspan=4, sticky="ew", pady=5)
        self._reg(ttk.Radiobutton(mode, text=_tr("Single File Mode"), variable=self.batch_mode, value=False, command=self.toggle_mode), "Single File Mode").grid(row=0, column=0, sticky="w")
        self._reg(ttk.Radiobutton(mode, text=_tr("Batch Mode (Multiple Files)"), variable=self.batch_mode, value=True, command=self.toggle_mode), "Batch Mode (Multiple Files)").grid(row=0, column=1, sticky="w")
        
        self.file_frame = self._reg(ttk.LabelFrame(main, text=_tr("File Selection"), padding=10), "File Selection")
        self.file_frame.grid(row=3, column=0, columnspan=4, sticky="ew", pady=10)
        self.single_frame = ttk.Frame(self.file_frame)
        self.single_frame.grid(row=0, column=0, columnspan=4, sticky="ew")
        self.bundle_path = tk.StringVar()
        self._reg(ttk.Label(self.single_frame, text=_tr("Asset Bundle File:")), "Asset Bundle File:").grid(row=0, column=0, sticky="w")
        ttk.Entry(self.single_frame, textvariable=self.bundle_path, width=60).grid(row=0, column=1, sticky="ew", padx=5)
        self._reg(ttk.Button(self.single_frame, text=_tr("Browse"), command=self.browse_single_bundle), "Browse").grid(row=0, column=2, padx=5)
        self.batch_frame = ttk.Frame(self.file_frame)
        bbtn = ttk.Frame(self.batch_frame); bbtn.grid(row=0, column=0, columnspan=4, sticky="ew", pady=5)
        self._reg(ttk.Button(bbtn, text=_tr("📁 Add Files"), command=self.add_batch_files), "📁 Add Files").grid(row=0, column=0, padx=5)
        self._reg(ttk.Button(bbtn, text=_tr("📂 Add Folder"), command=self.add_batch_folder), "📂 Add Folder").grid(row=0, column=1, padx=5)
        self._reg(ttk.Button(bbtn, text=_tr("📥 Scan 'modded'"), command=self.scan_modded_folder), "📥 Scan 'modded'").grid(row=0, column=2, padx=5)
        self._reg(ttk.Button(bbtn, text=_tr("🗑️ Clear All"), command=self.clear_batch_files), "🗑️ Clear All").grid(row=0, column=3, padx=5)
        lst = ttk.Frame(self.batch_frame); lst.grid(row=1, column=0, columnspan=4, sticky="nsew")
        self.file_listbox = tk.Listbox(lst, height=8, selectmode=tk.EXTENDED)
        ysb = ttk.Scrollbar(lst, orient="vertical", command=self.file_listbox.yview)
        self.file_listbox.configure(yscrollcommand=ysb.set)
        self.file_listbox.grid(row=0, column=0, sticky="nsew"); ysb.grid(row=0, column=1, sticky="ns")
        # Thumbnail preview of the currently highlighted file (body texture).
        self._preview_size = 160
        self._preview_imgref = None
        self._preview_token = 0
        prev = ttk.Frame(lst); prev.grid(row=0, column=2, padx=(10, 0), sticky="n")
        self._reg(ttk.Label(prev, text=_tr("Preview")), "Preview").grid(row=0, column=0)
        # Fixed-size box so the layout doesn't jump as thumbnails load. width/height
        # on a tk.Label are pixels only while an image is shown, so we wrap a sized,
        # non-propagating frame around the label instead.
        prevbox = tk.Frame(prev, width=self._preview_size, height=self._preview_size, bg="#15161b")
        prevbox.grid(row=1, column=0); prevbox.grid_propagate(False)
        self.preview_label = self._reg(tk.Label(prevbox, bg="#15161b", text=_tr("select a file"), fg="#888"), "select a file")
        self.preview_label.place(relx=0.5, rely=0.5, anchor="center")
        self.file_listbox.bind("<<ListboxSelect>>", self._on_file_select)
        lst.columnconfigure(0, weight=1); lst.rowconfigure(0, weight=1)
        self._reg(ttk.Button(self.batch_frame, text=_tr("Remove Selected"), command=self.remove_selected_files), "Remove Selected").grid(row=2, column=0, pady=5, sticky="w")
        
        out = self._reg(ttk.LabelFrame(main, text=_tr("Output Settings"), padding=10), "Output Settings")
        out.grid(row=4, column=0, columnspan=4, sticky="ew", pady=10)
        self._reg(ttk.Checkbutton(out, text=_tr("Output to location where target Bundle exists"), variable=self.output_to_bundle_location, command=self.toggle_output_location_mode), "Output to location where target Bundle exists").grid(row=0, column=0, columnspan=3, sticky="w", pady=5)
        self.manual_output_frame = ttk.Frame(out); self.manual_output_frame.grid(row=1, column=0, columnspan=4, sticky="ew")
        self._reg(ttk.Label(self.manual_output_frame, text=_tr("Output Directory:")), "Output Directory:").grid(row=0, column=0, sticky="w")
        ttk.Entry(self.manual_output_frame, textvariable=self.output_dir, width=60).grid(row=0, column=1, sticky="ew", padx=5)
        self._reg(ttk.Button(self.manual_output_frame, text=_tr("Browse"), command=self.browse_output), "Browse").grid(row=0, column=2, padx=5)
        
        settings = self._reg(ttk.LabelFrame(main, text=_tr("Settings"), padding=10), "Settings")
        settings.grid(row=5, column=0, columnspan=4, sticky="ew", pady=10)
        self._reg(ttk.Label(settings, text=_tr("Thumbnail Size:")), "Thumbnail Size:").grid(row=0, column=0, sticky="w")
        ttk.Spinbox(settings, from_=64, to=512, textvariable=self.thumbnail_size, width=10).grid(row=0, column=1, sticky="w", padx=5)
        self._reg(ttk.Label(settings, text=_tr("px")), "px").grid(row=0, column=2, sticky="w")
        cidf = ttk.Frame(settings); cidf.grid(row=1, column=0, columnspan=4, sticky="w", pady=5)
        self._reg(ttk.Checkbutton(cidf, text=_tr("Auto-detect Character ID (texture/filename)"), variable=self.auto_chara_id, command=self.toggle_chara_id_mode), "Auto-detect Character ID (texture/filename)").grid(row=0, column=0, sticky="w")
        self.manual_chara_frame = ttk.Frame(cidf); self.manual_chara_frame.grid(row=1, column=0, sticky="w", pady=5)
        self._reg(ttk.Label(self.manual_chara_frame, text=_tr("Manual Character ID:")), "Manual Character ID:").grid(row=0, column=0, sticky="w")
        ttk.Spinbox(self.manual_chara_frame, from_=1, to=999, textvariable=self.chara_id, width=10).grid(row=0, column=1, sticky="w", padx=5)
        
        platf = self._reg(ttk.LabelFrame(main, text=_tr("Platform (Android / iOS)"), padding=10), "Platform (Android / iOS)")
        platf.grid(row=6, column=0, columnspan=4, sticky="ew", pady=5)
        self._reg(ttk.Checkbutton(platf, text=_tr("Append platform suffix to zip name (_apk / _ios)"),
                        variable=self.append_platform_suffix), "Append platform suffix to zip name (_apk / _ios)").grid(row=0, column=0, sticky="w")
        self._reg(ttk.Checkbutton(platf, text=_tr("Combine detected Android+iOS pairs into one zip (name_apk_ios.zip)"),
                        variable=self.combine_pairs), "Combine detected Android+iOS pairs into one zip (name_apk_ios.zip)").grid(row=1, column=0, sticky="w")
        self._reg(ttk.Label(platf, text=_tr(_PK_PLATFORM_NOTE), foreground="gray"), _PK_PLATFORM_NOTE).grid(row=2, column=0, sticky="w", pady=(3, 0))

        ptxt = "🚀 Create Mod Package(s)" if UnityPy and PIL else "🚀 Create Mod Package(s) (UnityPy/Pillow required)"
        self.process_btn = self._reg(ttk.Button(main, text=_tr(ptxt), command=self.start_processing, state=("normal" if (UnityPy and PIL) else "disabled")), ptxt)
        self.process_btn.grid(row=7, column=0, columnspan=4, pady=20)

        prog = self._reg(ttk.LabelFrame(main, text=_tr("Progress"), padding=10), "Progress"); prog.grid(row=8, column=0, columnspan=4, sticky="ew", pady=5)
        self._reg(ttk.Label(prog, text=_tr("Overall Progress:")), "Overall Progress:").grid(row=0, column=0, sticky="w")
        self.overall_progress = ttk.Progressbar(prog, mode="determinate"); self.overall_progress.grid(row=0, column=1, sticky="ew", padx=5)
        self.overall_label = self._reg(ttk.Label(prog, text=_tr("0 / 0 files")), "0 / 0 files"); self.overall_label.grid(row=0, column=2, sticky="w", padx=5)
        self._reg(ttk.Label(prog, text=_tr("Current File:")), "Current File:").grid(row=1, column=0, sticky="w", pady=(5,0))
        self.current_progress = ttk.Progressbar(prog, mode="determinate"); self.current_progress.grid(row=1, column=1, sticky="ew", padx=5, pady=(5,0))
        self.current_label = self._reg(ttk.Label(prog, text=_tr("Ready")), "Ready"); self.current_label.grid(row=1, column=2, sticky="w", padx=5, pady=(5,0))

        logf = self._reg(ttk.LabelFrame(main, text=_tr("Processing Log"), padding=5), "Processing Log"); logf.grid(row=9, column=0, columnspan=4, sticky="nsew", pady=10)
        tf = ttk.Frame(logf); tf.grid(row=0, column=0, sticky="nsew")
        self.log_text = tk.Text(tf, height=10, width=90, wrap="word")
        ysb2 = ttk.Scrollbar(tf, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=ysb2.set)
        self.log_text.grid(row=0, column=0, sticky="nsew"); ysb2.grid(row=0, column=1, sticky="ns")

        self.root.columnconfigure(0, weight=1); self.root.rowconfigure(0, weight=1)
        main.columnconfigure(1, weight=1)
        logf.columnconfigure(0, weight=1); logf.rowconfigure(0, weight=1)
        tf.columnconfigure(0, weight=1); tf.rowconfigure(0, weight=1)
        self.file_frame.columnconfigure(1, weight=1)
        self.single_frame.columnconfigure(1, weight=1)
        self.batch_frame.columnconfigure(0, weight=1)
        
        self.toggle_mode()
        self.toggle_chara_id_mode()
        self.toggle_output_location_mode()
        self._apply_i18n()

    def install_requirements(self):
        self.log("🔄 Installing UnityPy/Pillow...")
        global UnityPy, PIL
        if UnityPy is None: UnityPy = ensure_unitypy()
        if PIL is None: PIL = ensure_pillow()
        if UnityPy and PIL:
            self.log("✅ Installation complete! Enabling buttons")
            self.process_btn.configure(state="normal", text=_tr("🚀 Create Mod Package(s)"))
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
        self.process_btn.config(text=(_tr("🚀 Create Mod Packages") if is_batch else _tr("🚀 Create Mod Package")))

    def toggle_chara_id_mode(self):
        state = "disabled" if self.auto_chara_id.get() else "normal"
        for child in self.manual_chara_frame.winfo_children():
            child.configure(state=state)

    def browse_single_bundle(self):
        fn = filedialog.askopenfilename(title=_tr("Select Asset Bundle File"),
                                        initialdir=default_sukusta_dir("modded"),
                                        filetypes=[("All files", "*.*")])
        if fn: self.bundle_path.set(fn); self.log(f"Selected: {os.path.basename(fn)}")

    def add_batch_files(self):
        fns = filedialog.askopenfilenames(title=_tr("Select Asset Bundle Files"),
                                          initialdir=default_sukusta_dir("modded"),
                                          filetypes=[("All files", "*.*")])
        count = 0
        for fn in fns:
            if fn not in self.bundle_files:
                self.bundle_files.append(fn); self.file_listbox.insert(tk.END, os.path.basename(fn)); count += 1
        self.log(f"Added {count} files. Total: {len(self.bundle_files)}")

    def add_batch_folder(self):
        folder = filedialog.askdirectory(title=_tr("Select Folder"), initialdir=default_sukusta_dir("modded"))
        if not folder: return
        added = 0
        for root, _, files in os.walk(folder):
            for f in files:
                p = os.path.join(root, f)
                if p not in self.bundle_files:
                    self.bundle_files.append(p)
                    self.file_listbox.insert(tk.END, os.path.relpath(p, folder)); added += 1
        self.log(f"Added {added} files from folder. Total: {len(self.bundle_files)}")

    def scan_modded_folder(self):
        """Quick-add every UnityFS bundle from the default sukusta/modded folder."""
        modded = default_sukusta_dir("modded")
        bundles = find_asset_bundles(modded)
        if not bundles:
            messagebox.showinfo(_tr("Scan 'modded'"),
                                _tr("No Unity asset bundles found in:\n{modded}", modded=modded))
            return
        added = 0
        for p in bundles:
            if p not in self.bundle_files:
                self.bundle_files.append(p)
                self.file_listbox.insert(tk.END, os.path.relpath(p, modded))
                added += 1
        self.log(f"📥 Scanned 'modded': added {added} bundle(s). Total: {len(self.bundle_files)}")

    def clear_batch_files(self):
        self.bundle_files.clear(); self.file_listbox.delete(0, tk.END); self.log("Cleared batch list.")
        self._clear_preview("select a file")

    def remove_selected_files(self):
        sel = self.file_listbox.curselection()
        if not sel: return
        for i in reversed(sel):
            del self.bundle_files[i]; self.file_listbox.delete(i)
        self.log(f"Removed {len(sel)} files.")
        self._clear_preview("select a file")

    def _clear_preview(self, text="select a file"):
        self._preview_imgref = None
        try:
            self.preview_label.configure(image="", text=text)
        except Exception:
            pass

    def _on_file_select(self, _event=None):
        """Show a thumbnail of the highlighted bundle (decoded in a worker thread
        so the UI never blocks; Termux uses a crash-safe child process)."""
        sel = self.file_listbox.curselection()
        if not sel or not (PIL and UnityPy):
            return
        idx = sel[0]
        if idx >= len(self.bundle_files):
            return
        path = self.bundle_files[idx]
        self._preview_token += 1
        token = self._preview_token
        self._clear_preview("loading…")

        def work():
            try:
                png, _label = build_thumbnail_for_bundle(path, size=self._preview_size, log=None)
            except Exception:
                png = None
            self.root.after(0, lambda: self._show_preview(token, png))

        threading.Thread(target=work, daemon=True).start()

    def _show_preview(self, token, png):
        if token != self._preview_token:
            return  # a newer selection superseded this one
        if not png:
            self._clear_preview("no preview")
            return
        try:
            from PIL import Image, ImageTk
            img = Image.open(io.BytesIO(png))
            self._preview_imgref = ImageTk.PhotoImage(img)
            self.preview_label.configure(image=self._preview_imgref, text="")
        except Exception:
            self._clear_preview("no preview")
        
    def browse_output(self):
        d = filedialog.askdirectory(title=_tr("Select Output Directory"),
                                    initialdir=default_sukusta_dir("suit"))
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
            if not self.bundle_files: messagebox.showerror(_tr("Error"), _tr("Please add files.")); return
            files = list(self.bundle_files)
        else:
            if not self.bundle_path.get() or not os.path.exists(self.bundle_path.get()):
                messagebox.showerror(_tr("Error"), _tr("Please select valid files.")); return
            files = [self.bundle_path.get()]

        self.is_processing = True
        self.process_btn.config(state="disabled", text=_tr("🔄 Processing..."))
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

        # ---- 플랫폼 감지 (Android / iOS) ----
        self.log("🔎 Detecting bundle platforms (Android / iOS)...")
        self.bundle_platforms = {}
        for p in masked_files_to_process:
            plat = detect_bundle_platform(p)
            self.bundle_platforms[p] = plat
            icon = {'android': '🤖', 'ios': '🍎'}.get(plat, '❓')
            self.log(f"  {icon} {os.path.basename(p)}: {plat if plat else 'unknown'}")

        # ---- 작업 목록 구성 (android+ios 페어는 하나로 묶음) ----
        jobs = build_pack_jobs(masked_files_to_process, self.bundle_platforms,
                               self.combine_pairs.get())
        pair_count = sum(1 for j in jobs if j[0] == 'pair')
        if self.combine_pairs.get():
            if pair_count:
                self.log(f"🔗 Matched {pair_count} Android+iOS pair(s) -> combined zip(s)")
            else:
                self.log("🟡 No Android+iOS pairs matched (files will be packed individually).")

        success, fail, skip = 0, 0, 0

        self.total_files = len(jobs)
        self.update_overall_progress(0, self.total_files)

        for i, job in enumerate(jobs):
            self.current_file_index = i + 1
            self.update_overall_progress(self.current_file_index - 1, self.total_files)

            if job[0] == 'pair':
                _, pair_key, android_path, ios_path = job
                label = f"{os.path.basename(android_path)} + {os.path.basename(ios_path)}"
                self.log(f"\n📦 Processing {self.current_file_index}/{self.total_files} (pair): {label}")
                self.update_current_status(f"Processing pair: {pair_key}")
                try:
                    result = self.process_pair(pair_key, android_path, ios_path)
                    if result: success += 1; self.log(f"✅ Success: {label}")
                    else: fail += 1; self.log(f"❌ Failed: {label}")
                except Exception as e:
                    fail += 1
                    self.log(f"❌ CRITICAL ERROR processing pair {pair_key}: {e}")
            else:
                bundle_path = job[1]
                bn = os.path.basename(bundle_path)
                self.log(f"\n📦 Processing {self.current_file_index}/{self.total_files}: {bn}")
                self.update_current_status(f"Processing: {bn}")
                try:
                    result = self.process_single_file(bundle_path,
                                                      platform=self.bundle_platforms.get(bundle_path))
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
        self.root.after(0, lambda: self.process_btn.config(state="normal", text=_tr("🚀 Create Mod Package(s)")))

    def process_single_file(self, bundle_path: str, platform=None, out_dir_override=None, force_suffix=False):
        """번들 하나를 zip으로 패키징한다.

        platform: 미리 감지된 플랫폼 ('android'/'ios'/None). None이면 여기서 감지.
        out_dir_override: 페어 묶음용 임시 출력 경로.
        force_suffix: 페어 내부 zip은 옵션과 무관하게 접미사를 강제한다 (이름 충돌 방지).
        반환: 성공 시 생성된 zip 경로, 실패 시 None.
        """
        bn_with_ext = os.path.basename(bundle_path)
        bn_no_ext = os.path.splitext(bn_with_ext)[0]

        if platform is None:
            platform = getattr(self, 'bundle_platforms', {}).get(bundle_path)
        if platform is None:
            platform = detect_bundle_platform(bundle_path)
        if platform is None and self.append_platform_suffix.get():
            self.log(f"❓ Platform unknown for '{bn_with_ext}' - zip name will have no platform suffix")

        self.update_current_progress(20); self.update_current_status("Extracting texture...")
        tex_name, tex_png_bytes = extract_body_texture_with_unitypy(bundle_path, log=self.log)

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
        thumb_bytes = make_thumbnail_png(tex_png_bytes, self.thumbnail_size.get()) if tex_png_bytes else make_name_thumbnail_png(bn_no_ext, self.thumbnail_size.get(), cid)
        if not thumb_bytes: self.log("❌ Thumbnail creation failed."); return None
        thumb_name = "im" + pack_safe_stem(bn_no_ext) + ".png"
        
        unmasked_bundle_path = None
        unmasked_filename = None
        
        if cid == 209 and bn_no_ext.lower().startswith("209rinamasked"):
            key = self.normalize_rina_key(bn_no_ext.lower())
            if key in self.rina_unmasked_map:
                unmasked_bundle_path = self.rina_unmasked_map[key]
                unmasked_filename = os.path.basename(unmasked_bundle_path)
                self.log(f"🎭 Paired '{bn_with_ext}' with '{unmasked_filename}'")
                # 가면 해제 모델의 플랫폼이 본체와 다르면 경고
                unmasked_platform = detect_bundle_platform(unmasked_bundle_path)
                if platform and unmasked_platform and unmasked_platform != platform:
                    self.log(f"⚠️ Platform mismatch! masked={platform}, unmasked={unmasked_platform} "
                             f"- the unmasked model will not load on {platform}")
            else:
                self.log(f"⚠️ Could not find a matching 'unmasked' file for key: '{key}'")

        if cid == 209 and not unmasked_bundle_path:
            self.log("❌ chara_id is 209 (Rina), which needs an unmasked model "
                     "('209rinaunmasked...') - none was found. Skipping this file "
                     "(the installer would crash). Add the unmasked file or set the correct chara ID.")
            return None

        self.update_current_progress(80); self.update_current_status("Creating modinstall.txt...")
        safe_costume = safe_arc_name(bn_with_ext)
        safe_unmask = safe_arc_name(unmasked_filename) if unmasked_filename else None
        modinstall = generate_modinstall_txt(bn_no_ext, safe_costume, thumb_name, cid, safe_unmask)
        
        if out_dir_override:
            out_dir = out_dir_override
        elif self.output_to_bundle_location.get():
            out_dir = os.path.dirname(os.path.abspath(bundle_path))
        else:
            out_dir = self.output_dir.get()

        append_suffix = self.append_platform_suffix.get() or force_suffix
        zip_base = compute_zip_basename(bn_no_ext, platform, append_suffix)
        out_zip = os.path.join(out_dir, f"{zip_base}.zip")
        
        self.update_current_status("Creating ZIP package...")
        ok = create_zip_package(out_zip, bundle_path, thumb_bytes, thumb_name, modinstall,
                                unmasked_bundle_path, masked_arcname=safe_costume,
                                unmasked_arcname=safe_unmask)
        
        if ok:
            self.update_current_progress(100)
            self.log(f"💾 Created: {os.path.basename(out_zip)}")
            return out_zip
        return None

    def process_pair(self, pair_key, android_path, ios_path):
        """Android+iOS 번들 한 쌍을 하나의 평면(flat) 합본 zip으로 만든다.

        zip 구성: 안드로이드 번들 + iOS 번들 + 썸네일 + modinstall.txt
        - modinstall의 costume_file은 안드로이드 번들을 가리키므로,
          구버전 인스톨러로 설치해도 안드로이드용이 올바르게 설치된다
          (iOS 번들은 구버전에서 무시됨).
        - 신버전 인스톨러는 costume_file_ios를 읽어 의상 1개로
          양쪽 플랫폼을 모두 등록한다."""
        and_name = os.path.basename(android_path)
        ios_name = os.path.basename(ios_path)
        and_no_ext = os.path.splitext(and_name)[0]

        # ---- 썸네일/캐릭터 ID: 안드로이드 번들 우선, 실패 시 iOS ----
        self.update_current_progress(20); self.update_current_status("Extracting texture...")
        tex_name, tex_png_bytes = extract_body_texture_with_unitypy(android_path, log=self.log)
        if not tex_png_bytes:
            tex_name, tex_png_bytes = extract_body_texture_with_unitypy(ios_path, log=self.log)

        self.update_current_progress(40); self.update_current_status("Detecting chara ID...")
        if self.auto_chara_id.get():
            cid_from_tex = extract_chara_id_from_texture_name(tex_name)
            cid_from_file = (extract_chara_id_from_filename(and_no_ext)
                             or extract_chara_id_from_filename(os.path.splitext(ios_name)[0]))
            cid = cid_from_tex or cid_from_file or self.chara_id.get()
            source = "texture" if cid_from_tex else "filename" if cid_from_file else "manual"
            self.log(f"🎯 Chara ID: {cid} (from {source})")
        else:
            cid = self.chara_id.get()
            self.log(f"👤 Manual Chara ID: {cid}")

        if and_no_ext.lower().startswith("209rinamasked") or os.path.splitext(ios_name)[0].lower().startswith("209rinamasked"):
            if cid != 209:
                self.log(f"⚠️ Overriding chara_id to 209 for Rina pair '{pair_key}'")
                cid = 209

        self.update_current_progress(60); self.update_current_status("Creating thumbnail...")
        thumb_bytes = make_thumbnail_png(tex_png_bytes, self.thumbnail_size.get()) if tex_png_bytes else make_name_thumbnail_png(pair_key, self.thumbnail_size.get(), cid)
        if not thumb_bytes:
            self.log("❌ Thumbnail creation failed.")
            return False
        thumb_name = "im" + pack_safe_stem(pair_key) + ".png"

        # ---- 리나(209) 가면 해제 페어: 플랫폼별로 각각 매칭 ----
        unmask_and_path = unmask_and_name = None
        unmask_ios_path = unmask_ios_name = None
        if cid == 209:
            key_and = self.normalize_rina_key(and_no_ext.lower())
            key_ios = self.normalize_rina_key(os.path.splitext(ios_name)[0].lower())
            if key_and in self.rina_unmasked_map:
                unmask_and_path = self.rina_unmasked_map[key_and]
                unmask_and_name = os.path.basename(unmask_and_path)
                self.log(f"🎭 Paired android '{and_name}' with '{unmask_and_name}'")
            else:
                self.log(f"⚠️ No android 'unmasked' match for key: '{key_and}'")
            if key_ios in self.rina_unmasked_map:
                unmask_ios_path = self.rina_unmasked_map[key_ios]
                unmask_ios_name = os.path.basename(unmask_ios_path)
                self.log(f"🎭 Paired ios '{ios_name}' with '{unmask_ios_name}'")
            else:
                self.log(f"⚠️ No ios 'unmasked' match for key: '{key_ios}'")

        if cid == 209 and not unmask_and_path:
            self.log("❌ chara_id is 209 (Rina), which needs an unmasked model "
                     "('209rinaunmasked...') - none was found. Skipping this pair "
                     "(the installer would crash). Add the unmasked file or set the correct chara ID.")
            return False

        self.update_current_progress(80); self.update_current_status("Creating modinstall.txt...")
        safe_and = safe_arc_name(and_name)
        safe_ios = safe_arc_name(ios_name)
        safe_unmask_and = safe_arc_name(unmask_and_name) if unmask_and_name else None
        safe_unmask_ios = safe_arc_name(unmask_ios_name) if unmask_ios_name else None
        modinstall = generate_modinstall_txt(pair_key, safe_and, thumb_name, cid,
                                             safe_unmask_and,
                                             ios_costume_filename=safe_ios,
                                             ios_unmask_filename=safe_unmask_ios)

        if self.output_to_bundle_location.get():
            out_dir = os.path.dirname(os.path.abspath(android_path))
        else:
            out_dir = self.output_dir.get()
        combined = os.path.join(out_dir, f"{pair_key}_apk_ios.zip")

        self.update_current_status("Creating combined ZIP package...")
        os.makedirs(os.path.dirname(combined), exist_ok=True)
        with zipfile.ZipFile(combined, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            zf.write(android_path, safe_and)
            zf.write(ios_path, safe_ios)
            if unmask_and_path and os.path.isfile(unmask_and_path):
                zf.write(unmask_and_path, safe_unmask_and)
            if unmask_ios_path and os.path.isfile(unmask_ios_path):
                zf.write(unmask_ios_path, safe_unmask_ios)
            zf.writestr(thumb_name, thumb_bytes)
            zf.writestr("modinstall.txt", modinstall.encode("utf-8"))

        self.update_current_progress(100)
        self.log(f"💾 Created combined package: {os.path.basename(combined)} "
                 f"(android={and_name}, ios={ios_name})")
        return True

    def show_completion_dialog(self, succ, fail):
        if self.output_to_bundle_location.get():
            folder = os.path.dirname(os.path.abspath(self.bundle_files[0])) if self.bundle_files else os.getcwd()
            loc_txt = _tr("Saved to each Bundle file location.")
        else:
            folder = self.output_dir.get()
            loc_txt = _tr("Output location: {folder}", folder=folder)
        
        msg = _tr(_PK_DONE_MSG, succ=succ, fail=fail, loc=loc_txt)
        icon = "info" if fail == 0 else "warning"
        
        if messagebox.askyesno(_tr("Processing Complete"), msg, icon=icon):
            try:
                if os.name == 'nt': os.startfile(folder)
                elif sys.platform == "darwin": subprocess.Popen(["open", folder])
                else: subprocess.Popen(["xdg-open", folder])
            except Exception: pass

def run_gui():
    if tk is None:
        print("tkinter is not available here; falling back to the text menu.")
        return run_menu()
    root = tk.Tk()
    app = UnityAssetBundleModPackerAutoCharaID(root)
    root.mainloop()


def build_parser():
    p = argparse.ArgumentParser(description="Unity costume mod packer (modded -> suit).")
    p.add_argument("--gui", action="store_true", help="force the desktop (tkinter) GUI")
    p.add_argument("--web", action="store_true",
                   help="launch the browser GUI (works on Termux; open it on your phone)")
    p.add_argument("--host", default="127.0.0.1", help="web GUI bind host (default 127.0.0.1)")
    p.add_argument("--port", type=int, default=8000, help="web GUI port (default 8000)")
    p.add_argument("--menu", "--cli", dest="menu", action="store_true",
                   help="force the Termux/headless text menu (modded -> suit)")
    return p


def main():
    # Hidden subcommand: decode one bundle's body texture in this (child) process.
    # Used by _decode_texture_via_subprocess so a native-decoder crash is isolated.
    if len(sys.argv) >= 4 and sys.argv[1] == "--decode-worker":
        return _decode_worker_main(sys.argv[2], sys.argv[3])

    args = build_parser().parse_args()
    if args.web:
        return run_web(host=args.host, port=args.port)
    if args.menu:
        return run_menu()
    if args.gui:
        return run_gui()
    if gui_available():
        return run_gui()
    return run_menu()


if __name__ == "__main__":
    main()
