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
import struct
import lzma

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
        # macOS는 기본 폰트/위젯 패딩이 커서 같은 높이에 내용이 덜 들어간다.
        # 플랫폼별로 기본 크기를 다르게 주고, 작은 화면을 대비해 스크롤도 둔다.
        if sys.platform == "darwin":
            self.root.geometry("1000x820")
        else:
            self.root.geometry("1000x800")
        self.root.minsize(760, 480)
        self.root.resizable(True, True)
        
        self.bundle_files = []
        self.output_dir = tk.StringVar(value=os.getcwd())
        self.thumbnail_size = tk.IntVar(value=256)
        self.chara_id = tk.IntVar(value=209) # Default for Rina
        self.auto_chara_id = tk.BooleanVar(value=True)
        self.batch_mode = tk.BooleanVar(value=True) # Default to batch
        self.output_to_bundle_location = tk.BooleanVar(value=False)
        self.append_platform_suffix = tk.BooleanVar(value=True)
        self.combine_pairs = tk.BooleanVar(value=True)
        self.is_processing = False
        self.current_file_index = 0
        self.total_files = 0
        
        self.rina_unmasked_map = {}
        self.bundle_platforms = {}
        
        self.setup_ui()

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
        
        platf = ttk.LabelFrame(main, text="Platform (Android / iOS)", padding=10)
        platf.grid(row=6, column=0, columnspan=4, sticky="ew", pady=5)
        ttk.Checkbutton(platf, text="Append platform suffix to zip name (_apk / _ios)",
                        variable=self.append_platform_suffix).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(platf, text="Combine detected Android+iOS pairs into one zip (name_apk_ios.zip)",
                        variable=self.combine_pairs).grid(row=1, column=0, sticky="w")
        ttk.Label(platf, text="Platform is read from each bundle's Unity header. Pairs are matched by filename ignoring apk/android/ios tokens.",
                  foreground="gray").grid(row=2, column=0, sticky="w", pady=(3, 0))

        ptxt = "🚀 Create Mod Package(s)" if UnityPy and PIL else "🚀 Create Mod Package(s) (UnityPy/Pillow required)"
        self.process_btn = ttk.Button(main, text=ptxt, command=self.start_processing, state=("normal" if (UnityPy and PIL) else "disabled"))
        self.process_btn.grid(row=7, column=0, columnspan=4, pady=20)

        prog = ttk.LabelFrame(main, text="Progress", padding=10); prog.grid(row=8, column=0, columnspan=4, sticky="ew", pady=5)
        ttk.Label(prog, text="Overall Progress:").grid(row=0, column=0, sticky="w")
        self.overall_progress = ttk.Progressbar(prog, mode="determinate"); self.overall_progress.grid(row=0, column=1, sticky="ew", padx=5)
        self.overall_label = ttk.Label(prog, text="0 / 0 files"); self.overall_label.grid(row=0, column=2, sticky="w", padx=5)
        ttk.Label(prog, text="Current File:").grid(row=1, column=0, sticky="w", pady=(5,0))
        self.current_progress = ttk.Progressbar(prog, mode="determinate"); self.current_progress.grid(row=1, column=1, sticky="ew", padx=5, pady=(5,0))
        self.current_label = ttk.Label(prog, text="Ready"); self.current_label.grid(row=1, column=2, sticky="w", padx=5, pady=(5,0))

        logf = ttk.LabelFrame(main, text="Processing Log", padding=5); logf.grid(row=9, column=0, columnspan=4, sticky="nsew", pady=10)
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
        self.root.after(0, lambda: self.process_btn.config(state="normal", text="🚀 Create Mod Package(s)"))

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
        if not thumb_bytes: self.log("❌ Thumbnail creation failed."); return None
        thumb_name = f"im{bn_no_ext}.png"
        
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
        
        self.update_current_progress(80); self.update_current_status("Creating modinstall.txt...")
        modinstall = generate_modinstall_txt(bn_no_ext, bn_with_ext, thumb_name, cid, unmasked_filename)
        
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
        ok = create_zip_package(out_zip, bundle_path, thumb_bytes, thumb_name, modinstall, unmasked_bundle_path)
        
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
        tex_name, tex_png_bytes = extract_body_texture_with_unitypy(android_path)
        if not tex_png_bytes:
            tex_name, tex_png_bytes = extract_body_texture_with_unitypy(ios_path)

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
        thumb_bytes = make_thumbnail_png(tex_png_bytes, self.thumbnail_size.get()) if tex_png_bytes else make_placeholder_thumbnail_png("No Body Texture", self.thumbnail_size.get())
        if not thumb_bytes:
            self.log("❌ Thumbnail creation failed.")
            return False
        thumb_name = f"im{pair_key}.png"

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

        self.update_current_progress(80); self.update_current_status("Creating modinstall.txt...")
        modinstall = generate_modinstall_txt(pair_key, and_name, thumb_name, cid,
                                             unmask_and_name,
                                             ios_costume_filename=ios_name,
                                             ios_unmask_filename=unmask_ios_name)

        if self.output_to_bundle_location.get():
            out_dir = os.path.dirname(os.path.abspath(android_path))
        else:
            out_dir = self.output_dir.get()
        combined = os.path.join(out_dir, f"{pair_key}_apk_ios.zip")

        self.update_current_status("Creating combined ZIP package...")
        os.makedirs(os.path.dirname(combined), exist_ok=True)
        with zipfile.ZipFile(combined, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            zf.write(android_path, and_name)
            zf.write(ios_path, ios_name)
            if unmask_and_path and os.path.isfile(unmask_and_path):
                zf.write(unmask_and_path, unmask_and_name)
            if unmask_ios_path and os.path.isfile(unmask_ios_path):
                zf.write(unmask_ios_path, unmask_ios_name)
            zf.writestr(thumb_name, thumb_bytes)
            zf.writestr("modinstall.txt", modinstall.encode("utf-8"))

        self.update_current_progress(100)
        self.log(f"💾 Created combined package: {os.path.basename(combined)} "
                 f"(android={and_name}, ios={ios_name})")
        return True

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
