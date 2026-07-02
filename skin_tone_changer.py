# skin_tone_changer.py
# SIFAS Skin-Tone Changer (Single / Batch / GUI / CLI / Menu)
#
# Converts a SIFAS body/hand texture from one official skin-tone class to
# another by applying a per-channel linear map  out = clip(in * a + b)  that
# was fitted against the recreation texture set in the `elichika` repo
# (sdk/costume/texture/original).
#
# The four tone classes and which characters use them:
#   bright       Guilty Kiss, AZUNA, Eli, Nico, Dia, Ai, Emma, Shioriko, Mia
#   default      CYaRon, Printemps, Umi, Maki, Kanan, Hanamaru, Kasumi,
#                Karin, Kanata, Rina
#   slight       Nozomi, Lanzhu
#   medium_tone  Rin
#
# How the maps were derived & verified (reproduce with --selftest <ref_dir>):
#   * bright / default / medium_tone are the SAME skin painting recoloured, so
#     on the aligned skin region a single per-channel linear map reproduces the
#     conversion to ~1% (test RMSE 1.3-2.9 / 255).
#   * The three sit on ONE "tone axis" (cos(default->bright, default->medium)
#     = -0.98); every map here is anchored through `default` for consistency.
#   * `slight` is a separately drawn painting, so no per-pixel map is exact;
#     its maps are the best linear approximation (test RMSE ~7), matching the
#     overall tone but not fine detail. Use --skin-only / lower --strength to
#     taste, then hand-touch if needed.
#
# Requirements: pip install Pillow numpy
#   (numpy is only needed for the actual pixel work; both are auto-installed.)

import os
import sys
import json
import argparse


# ---------------------------------------------------------------------------
# Language choice, shared & persisted with the other SIFAS tools.
# ---------------------------------------------------------------------------
class _LangStore:
    @staticmethod
    def _path():
        if os.name == "nt":
            base = os.environ.get("APPDATA") or os.path.join(
                os.path.expanduser("~"), "AppData", "Roaming")
        else:
            base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
                os.path.expanduser("~"), ".config")
        return os.path.join(base, "sifas_modding_tools", "config.json")

    def get_language(self):
        try:
            with open(self._path(), encoding="utf-8") as f:
                return json.load(f).get("language")
        except Exception:
            return None

    def set_language(self, code):
        try:
            p = self._path()
            os.makedirs(os.path.dirname(p), exist_ok=True)
            data = {}
            try:
                with open(p, encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                pass
            data["language"] = code
            with open(p, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass


def _ensure_deps():
    """Make sure Pillow and numpy are importable; install if missing."""
    missing = []
    try:
        import PIL  # noqa: F401
    except ImportError:
        missing.append("Pillow")
    try:
        import numpy  # noqa: F401
    except ImportError:
        missing.append("numpy")
    if missing:
        import subprocess
        print("Installing missing dependencies: " + ", ".join(missing))
        subprocess.check_call([sys.executable, "-m", "pip", "install"] + missing)


_ensure_deps()

import numpy as np            # noqa: E402
from PIL import Image          # noqa: E402


# ===========================================================================
# Tone model -- constants fitted from sdk/costume/texture/original.
# Each map is per-channel  out_c = in_c * a_c + b_c  (a, b ordered R, G, B).
# Anchored through `default` so the set is internally consistent; see
# --selftest to reproduce every number from the reference textures.
# ===========================================================================
TONES = ["bright", "default", "slight", "medium_tone"]

SKIN_TONE_MAPS = {
    ("bright", "default"):      ((1.19907, 0.93389, 0.91160), (-48.2111,   7.7997,   9.1088)),
    ("bright", "slight"):       ((1.08141, 1.05401, 0.95964), (-23.0708, -13.9049,   5.5764)),
    ("bright", "medium_tone"):  ((1.23472, 0.88606, 0.82263), (-58.7773,  13.0090,  20.2567)),
    ("default", "bright"):      ((0.83398, 1.07079, 1.09697), ( 40.2073,  -8.3518,  -9.9921)),
    ("default", "slight"):      ((0.90188, 1.12862, 1.05270), ( 20.4097, -22.7077,  -4.0124)),
    ("default", "medium_tone"): ((1.02973, 0.94878, 0.90240), ( -9.1327,   5.6088,  12.0370)),
    ("slight", "bright"):       ((0.92472, 0.94876, 1.04206), ( 21.3340,  13.1924,  -5.8110)),
    ("slight", "default"):      ((1.10880, 0.88604, 0.94994), (-22.6303,  20.1200,   3.8115)),
    ("slight", "medium_tone"):  ((1.14177, 0.84065, 0.85723), (-32.4359,  24.6982,  15.4765)),
    ("medium_tone", "bright"):  ((0.80990, 1.12860, 1.21561), ( 47.6039, -14.6819, -24.6244)),
    ("medium_tone", "default"): ((0.97113, 1.05399, 1.10816), (  8.8690,  -5.9116, -13.3388)),
    ("medium_tone", "slight"):  ((0.87584, 1.18955, 1.16655), ( 28.4085, -29.3797, -18.0541)),
}

# Mean skin RGB of each reference tone, used by --from auto to guess the source.
REF_SKIN_MEAN = {
    "bright":      (237.67, 210.14, 189.17),
    "default":     (219.81, 190.67, 156.66),
    "slight":      (222.59, 194.58, 177.84),
    "medium_tone": (212.24, 187.15, 161.47),
}

# `slight` cannot be reproduced per-pixel; flag conversions touching it.
APPROX_TONES = {"slight"}

IMG_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".tga", ".webp")


# ===========================================================================
# Core conversion (pure, GUI-free, unit-testable).
# ===========================================================================
def _skin_mask(rgb, alpha=None):
    """Boolean mask of warm pinkish skin pixels. `rgb` is HxWx3 float."""
    R, G, B = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    m = (R > 150) & (R > G) & (G >= B - 3) & ((R - B) > 10) & ((R - B) < 140) & (G > 95)
    if alpha is not None:
        m &= alpha > 16
    return m


def _box_blur(m, r):
    """Separable box blur of a float array, used to feather the skin mask."""
    if r <= 0:
        return m
    m = m.astype(np.float64)
    for axis in (0, 1):
        n = m.shape[axis]
        pad = [(0, 0), (0, 0)]
        pad[axis] = (r + 1, r)
        c = np.cumsum(np.pad(m, pad, mode="edge"), axis=axis)
        hi = [slice(None), slice(None)]
        lo = [slice(None), slice(None)]
        hi[axis] = slice(2 * r + 1, 2 * r + 1 + n)
        lo[axis] = slice(0, n)
        m = (c[tuple(hi)] - c[tuple(lo)]) / (2 * r + 1)
    return m


def detect_tone(rgb, alpha=None):
    """Guess the source tone class from a texture's mean skin colour."""
    mask = _skin_mask(rgb, alpha)
    if mask.sum() < 200:
        return None
    mean = rgb[mask].mean(0)
    return min(TONES, key=lambda t: float(np.linalg.norm(mean - np.array(REF_SKIN_MEAN[t]))))


def convert_array(rgb, src, dst, skin_only=False, strength=1.0, mask=None):
    """Apply the src->dst tone map to an HxWx3 float array (0-255).

    skin_only feathers the change onto colour-detected skin only; strength (0-1)
    scales how far the conversion is taken. If `mask` (an HxW array in 0..1, e.g. a
    UV/bone-derived skin region) is given it is used as the spatial gate instead of
    the colour detector, feathered the same way. Returns a float array (0-255).
    """
    rgb = rgb.astype(np.float64)
    if src == dst or strength <= 0:
        return rgb.copy()
    a, b = SKIN_TONE_MAPS[(src, dst)]
    conv = np.clip(rgb * np.array(a) + np.array(b), 0, 255)
    alpha = float(np.clip(strength, 0, 1))
    if mask is not None:
        soft = _box_blur(np.asarray(mask, dtype=np.float64), 4)
        amt = np.clip(soft, 0, 1)[..., None] * alpha
    elif skin_only:
        soft = _box_blur(_skin_mask(rgb).astype(np.float64), 4)
        soft = np.clip(soft, 0, 1)[..., None]
        amt = soft * alpha
    else:
        amt = alpha
    return rgb * (1 - amt) + conv * amt


def convert_image(img, src, dst, skin_only=False, strength=1.0):
    """Convert a PIL image, preserving any alpha channel. Returns a PIL image."""
    has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
    base = img.convert("RGBA") if has_alpha else img.convert("RGB")
    arr = np.asarray(base).astype(np.float64)
    if has_alpha:
        rgb, al = arr[..., :3], arr[..., 3]
    else:
        rgb, al = arr, None
    if src == "auto":
        src = detect_tone(rgb, al) or "default"
    out = convert_array(rgb, src, dst, skin_only, strength)
    out = np.clip(out, 0, 255).astype(np.uint8)
    if has_alpha:
        out = np.dstack([out, al.astype(np.uint8)])
        return Image.fromarray(out, "RGBA"), src
    return Image.fromarray(out, "RGB"), src


def convert_file(in_path, out_path, src, dst, skin_only=False, strength=1.0, log=print):
    img = Image.open(in_path)
    result, used_src = convert_image(img, src, dst, skin_only, strength)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    result.save(out_path)
    note = ""
    if src == "auto":
        note = f" (detected source: {used_src})"
    if used_src in APPROX_TONES or dst in APPROX_TONES:
        note += "  [approx: slight]"
    if log:
        log(f"OK   {os.path.basename(in_path)} -> {os.path.basename(out_path)}"
            f"  [{used_src}->{dst}]{note}")
    return used_src


# ===========================================================================
# Batch
# ===========================================================================
def iter_images(folder, recursive=True):
    if os.path.isfile(folder):
        yield folder
        return
    if recursive:
        for root, _, files in os.walk(folder):
            for fn in sorted(files):
                if fn.lower().endswith(IMG_EXTS):
                    yield os.path.join(root, fn)
    else:
        for fn in sorted(os.listdir(folder)):
            fp = os.path.join(folder, fn)
            if os.path.isfile(fp) and fn.lower().endswith(IMG_EXTS):
                yield fp


def run_batch(in_dir, out_dir, src, dst, suffix, skin_only=False, strength=1.0,
              recursive=True, log=print, should_stop=lambda: False):
    files = list(iter_images(in_dir, recursive))
    total = len(files)
    ok = fail = 0
    for i, fp in enumerate(files, 1):
        if should_stop():
            log("[stopped]")
            break
        rel = os.path.relpath(fp, in_dir) if os.path.isdir(in_dir) else os.path.basename(fp)
        stem, ext = os.path.splitext(rel)
        out_path = os.path.join(out_dir, stem + suffix + ext)
        try:
            convert_file(fp, out_path, src, dst, skin_only, strength, log)
            ok += 1
        except Exception as exc:  # noqa: BLE001
            fail += 1
            log(f"FAIL {os.path.basename(fp)}: {exc}")
    log(f"Done. images={total}  ok={ok}  fail={fail}")
    return ok, fail, total


# ===========================================================================
# Verification / self-test against the reference texture set.
# ===========================================================================
def selftest(ref_dir, log=print):
    """Re-derive nothing; just measure how well the embedded maps reproduce the
    reference conversions. Pass the folder holding bright/default/slight/
    medium_tone .png (e.g. elichika/sdk/costume/texture/original)."""
    def load(t):
        for cand in (t, t.replace("_", ""), t.replace("_", " ")):
            p = os.path.join(ref_dir, cand + ".png")
            if os.path.exists(p):
                return np.asarray(Image.open(p).convert("RGB")).astype(np.float64)
        raise FileNotFoundError(f"{t}.png not found in {ref_dir}")

    arr = {t: load(t) for t in TONES}
    masks = {t: _skin_mask(arr[t]) for t in TONES}
    common = np.ones(arr["default"].shape[:2], bool)
    for t in TONES:
        common &= masks[t]
    # erode a little so we score interior skin, not seams
    for _ in range(3):
        e = common.copy()
        e[1:, :] &= common[:-1, :]; e[:-1, :] &= common[1:, :]
        e[:, 1:] &= common[:, :-1]; e[:, :-1] &= common[:, 1:]
        common = e
    test = np.where(common.ravel())[0][1::2]  # held-out half

    log(f"verification on {len(test)} held-out skin pixels (RMSE / 255):")
    header = "src\\dst".ljust(13) + "".join(t.rjust(13) for t in TONES)
    log(header)
    worst = 0.0
    for s in TONES:
        row = s.ljust(13)
        X = arr[s].reshape(-1, 3)[test]
        for d in TONES:
            Y = arr[d].reshape(-1, 3)[test]
            if s == d:
                rmse = 0.0
            else:
                a, b = SKIN_TONE_MAPS[(s, d)]
                pred = np.clip(X * np.array(a) + np.array(b), 0, 255)
                rmse = float(np.sqrt(((pred - Y) ** 2).mean()))
                if d not in APPROX_TONES and s not in APPROX_TONES:
                    worst = max(worst, rmse)
            row += f"{rmse:13.2f}"
        log(row)
    log(f"\nworst exact-tone RMSE (excludes 'slight') = {worst:.2f} / 255"
        f"  ->  {'PASS' if worst < 5 else 'CHECK'} (expect < 5)")
    log("'slight' rows/cols are intentionally approximate (~7); see header notes.")
    return worst


# ===========================================================================
# Translations
# ===========================================================================
STRINGS = {
    "en": {
        "title": "SIFAS Skin-Tone Changer",
        "language": "Language:",
        "from": "Source tone:", "to": "Target tone:",
        "auto": "auto-detect",
        "mode_single": "Single image", "mode_batch": "Folder (batch)",
        "input_file": "Image file:", "input_dir": "Input folder:",
        "out_dir": "Output folder (blank = beside input):",
        "suffix": "Filename suffix:",
        "skin_only": "Recolour skin only (keep costume colours)",
        "strength": "Strength:",
        "browse": "Browse", "convert": "Convert", "preview": "Preview",
        "before": "Before", "after": "After",
        "log": "Log", "done": "Done.",
        "err": "Error", "warn": "Warning",
        "err_same": "Source and target tone are the same.",
        "err_input": "Choose an input image or folder first.",
        "approx_note": "Note: 'slight' is approximate (matches overall tone, not fine detail).",
    },
    "ko": {
        "title": "SIFAS 피부톤 변환기",
        "language": "언어:",
        "from": "원본 톤:", "to": "대상 톤:",
        "auto": "자동 감지",
        "mode_single": "단일 이미지", "mode_batch": "폴더 (일괄)",
        "input_file": "이미지 파일:", "input_dir": "입력 폴더:",
        "out_dir": "출력 폴더 (비우면 입력 옆):",
        "suffix": "파일명 접미사:",
        "skin_only": "피부만 변환 (코스튬 색 유지)",
        "strength": "강도:",
        "browse": "찾아보기", "convert": "변환", "preview": "미리보기",
        "before": "변환 전", "after": "변환 후",
        "log": "로그", "done": "완료.",
        "err": "오류", "warn": "경고",
        "err_same": "원본 톤과 대상 톤이 같습니다.",
        "err_input": "먼저 입력 이미지나 폴더를 선택하세요.",
        "approx_note": "참고: 'slight'는 근사 변환입니다(전체 톤은 맞추되 세부는 다를 수 있음).",
    },
    "ja": {
        "title": "SIFAS 肌トーン変換ツール",
        "language": "言語:",
        "from": "元のトーン:", "to": "変換後のトーン:",
        "auto": "自動検出",
        "mode_single": "単一画像", "mode_batch": "フォルダ (一括)",
        "input_file": "画像ファイル:", "input_dir": "入力フォルダ:",
        "out_dir": "出力フォルダ (空欄=入力の隣):",
        "suffix": "ファイル名サフィックス:",
        "skin_only": "肌のみ変換 (衣装の色は保持)",
        "strength": "強さ:",
        "browse": "参照", "convert": "変換", "preview": "プレビュー",
        "before": "変換前", "after": "変換後",
        "log": "ログ", "done": "完了。",
        "err": "エラー", "warn": "警告",
        "err_same": "元と変換後のトーンが同じです。",
        "err_input": "先に入力画像かフォルダを選んでください。",
        "approx_note": "注: 'slight' は近似変換です（全体のトーンは合わせますが細部は異なる場合があります）。",
    },
}


def make_t(lang):
    table = STRINGS.get(lang, STRINGS["en"])
    return lambda k: table.get(k, STRINGS["en"].get(k, k))


# ===========================================================================
# CLI
# ===========================================================================
def run_cli(argv):
    p = argparse.ArgumentParser(
        prog="skin_tone_changer.py",
        description="Convert SIFAS textures between skin-tone classes "
                    "(bright / default / slight / medium_tone).")
    p.add_argument("input", nargs="?", help="image file or folder")
    p.add_argument("--from", dest="src", default="auto",
                   choices=["auto"] + TONES, help="source tone (default: auto)")
    p.add_argument("--to", dest="dst", choices=TONES, help="target tone")
    p.add_argument("--out", help="output file or folder (default: beside input)")
    p.add_argument("--suffix", help="filename suffix (default: _<target>)")
    p.add_argument("--skin-only", action="store_true",
                   help="recolour detected skin only, keep costume colours")
    p.add_argument("--strength", type=float, default=1.0,
                   help="0..1 conversion strength (default: 1.0)")
    p.add_argument("--no-recursive", action="store_true",
                   help="do not descend into sub-folders in batch mode")
    p.add_argument("--selftest", metavar="REF_DIR",
                   help="verify embedded maps against a reference texture folder")
    args = p.parse_args(argv)

    if args.selftest:
        worst = selftest(args.selftest)
        return 0 if worst < 5 else 2

    if not args.input or not args.dst:
        p.error("need INPUT and --to (or use --selftest); run with no args for the GUI/menu")

    suffix = args.suffix if args.suffix is not None else f"_{args.dst}"
    if os.path.isdir(args.input):
        out_dir = args.out or (args.input.rstrip("/\\") + "_converted")
        run_batch(args.input, out_dir, args.src, args.dst, suffix,
                  args.skin_only, args.strength, not args.no_recursive)
    else:
        if args.out:
            out_path = args.out
        else:
            stem, ext = os.path.splitext(args.input)
            out_path = stem + suffix + ext
        convert_file(args.input, out_path, args.src, args.dst,
                     args.skin_only, args.strength)
    return 0


# ===========================================================================
# Headless text menu (Termux / no display)
# ===========================================================================
def run_menu():
    print("=== SIFAS Skin-Tone Changer (text menu) ===")
    print("Tones: " + ", ".join(TONES))
    inp = input("Input image or folder path: ").strip().strip('"')
    if not inp or not os.path.exists(inp):
        print("Path not found."); return 1

    def pick(prompt, options):
        for i, o in enumerate(options, 1):
            print(f"  {i}. {o}")
        while True:
            s = input(prompt).strip()
            if s.isdigit() and 1 <= int(s) <= len(options):
                return options[int(s) - 1]
            print("  ?")

    src = pick("Source tone #: ", ["auto"] + TONES)
    dst = pick("Target tone #: ", TONES)
    if src == dst:
        print("Source and target are the same; nothing to do."); return 1
    skin_only = input("Skin only? (keep costume colours) [y/N]: ").strip().lower() == "y"
    s = input("Strength 0..1 [1.0]: ").strip()
    strength = float(s) if s else 1.0
    suffix = input(f"Suffix [_{dst}]: ").strip() or f"_{dst}"

    if os.path.isdir(inp):
        out_dir = input("Output folder [<input>_converted]: ").strip() or (inp.rstrip("/\\") + "_converted")
        run_batch(inp, out_dir, src, dst, suffix, skin_only, strength)
    else:
        stem, ext = os.path.splitext(inp)
        convert_file(inp, stem + suffix + ext, src, dst, skin_only, strength)
    if dst in APPROX_TONES or src in APPROX_TONES:
        print(make_t("en")("approx_note"))
    return 0


# ===========================================================================
# GUI
# ===========================================================================
def gui_available():
    if "com.termux" in (os.environ.get("PREFIX", "") + os.environ.get("HOME", "")):
        return False
    if os.path.isdir("/data/data/com.termux"):
        return False
    try:
        import tkinter  # noqa: F401
    except Exception:
        return False
    if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
        return False
    return True


class App:
    def __init__(self, root):
        import tkinter as tk
        from tkinter import ttk
        self.tk = tk
        self.ttk = ttk
        self.root = root
        self.lang = _LangStore().get_language() or "en"
        self.t = make_t(self.lang)
        self._preview_imgs = []
        self._build()

    def _build(self):
        import tkinter as tk
        from tkinter import ttk, scrolledtext
        t = self.t
        self.root.title(t("title"))
        self.root.geometry("760x680")
        pad = {"padx": 6, "pady": 4}

        top = ttk.Frame(self.root); top.pack(fill="x", **pad)
        ttk.Label(top, text=t("language")).pack(side="left")
        self.lang_var = tk.StringVar(value=self.lang)
        lang_box = ttk.Combobox(top, textvariable=self.lang_var, width=6,
                                values=["en", "ko", "ja"], state="readonly")
        lang_box.pack(side="left", padx=4)
        lang_box.bind("<<ComboboxSelected>>", self._on_lang)

        tones = ttk.Frame(self.root); tones.pack(fill="x", **pad)
        ttk.Label(tones, text=t("from")).grid(row=0, column=0, sticky="e")
        self.src_var = tk.StringVar(value="auto")
        ttk.Combobox(tones, textvariable=self.src_var, width=14, state="readonly",
                     values=["auto"] + TONES).grid(row=0, column=1, padx=4)
        ttk.Label(tones, text=t("to")).grid(row=0, column=2, sticky="e")
        self.dst_var = tk.StringVar(value="bright")
        ttk.Combobox(tones, textvariable=self.dst_var, width=14, state="readonly",
                     values=TONES).grid(row=0, column=3, padx=4)

        mode = ttk.Frame(self.root); mode.pack(fill="x", **pad)
        self.mode_var = tk.StringVar(value="single")
        ttk.Radiobutton(mode, text=t("mode_single"), variable=self.mode_var,
                        value="single", command=self._sync).pack(side="left")
        ttk.Radiobutton(mode, text=t("mode_batch"), variable=self.mode_var,
                        value="batch", command=self._sync).pack(side="left", padx=10)

        io = ttk.Frame(self.root); io.pack(fill="x", **pad)
        self.in_var = tk.StringVar()
        self.in_label = ttk.Label(io, text=t("input_file"))
        self.in_label.grid(row=0, column=0, sticky="e")
        ttk.Entry(io, textvariable=self.in_var, width=58).grid(row=0, column=1, padx=4)
        ttk.Button(io, text=t("browse"), command=self._browse_in).grid(row=0, column=2)
        ttk.Label(io, text=t("out_dir")).grid(row=1, column=0, sticky="e")
        self.out_var = tk.StringVar()
        ttk.Entry(io, textvariable=self.out_var, width=58).grid(row=1, column=1, padx=4)
        ttk.Button(io, text=t("browse"), command=self._browse_out).grid(row=1, column=2)
        ttk.Label(io, text=t("suffix")).grid(row=2, column=0, sticky="e")
        self.suffix_var = tk.StringVar(value="")
        ttk.Entry(io, textvariable=self.suffix_var, width=20).grid(row=2, column=1, sticky="w", padx=4)

        opts = ttk.Frame(self.root); opts.pack(fill="x", **pad)
        self.skin_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opts, text=t("skin_only"), variable=self.skin_var).pack(side="left")
        ttk.Label(opts, text=t("strength")).pack(side="left", padx=(16, 2))
        self.strength_var = tk.DoubleVar(value=1.0)
        ttk.Scale(opts, from_=0.0, to=1.0, variable=self.strength_var,
                  orient="horizontal", length=160).pack(side="left")

        btns = ttk.Frame(self.root); btns.pack(fill="x", **pad)
        ttk.Button(btns, text=t("preview"), command=self._preview).pack(side="left")
        ttk.Button(btns, text=t("convert"), command=self._convert).pack(side="left", padx=8)

        prev = ttk.Frame(self.root); prev.pack(fill="x", **pad)
        self.before_lbl = ttk.Label(prev, text=t("before"))
        self.before_lbl.grid(row=0, column=0)
        self.after_lbl = ttk.Label(prev, text=t("after"))
        self.after_lbl.grid(row=0, column=1, padx=8)

        ttk.Label(self.root, text=t("log")).pack(anchor="w", padx=6)
        self.log_box = scrolledtext.ScrolledText(self.root, height=10)
        self.log_box.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        self._sync()

    def _on_lang(self, _=None):
        self.lang = self.lang_var.get()
        _LangStore().set_language(self.lang)
        self.t = make_t(self.lang)
        for w in self.root.winfo_children():
            w.destroy()
        self._build()

    def _sync(self):
        batch = self.mode_var.get() == "batch"
        self.in_label.config(text=self.t("input_dir") if batch else self.t("input_file"))

    def log(self, msg):
        self.log_box.insert("end", msg + "\n")
        self.log_box.see("end")
        self.root.update_idletasks()

    def _browse_in(self):
        from tkinter import filedialog
        if self.mode_var.get() == "batch":
            d = filedialog.askdirectory()
        else:
            d = filedialog.askopenfilename(
                filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp *.tga *.webp"), ("All", "*.*")])
        if d:
            self.in_var.set(d)

    def _browse_out(self):
        from tkinter import filedialog
        d = filedialog.askdirectory()
        if d:
            self.out_var.set(d)

    def _show_preview(self, before_img, after_img):
        from PIL import ImageTk
        self._preview_imgs = []
        for img, lbl, cap in ((before_img, self.before_lbl, self.t("before")),
                              (after_img, self.after_lbl, self.t("after"))):
            thumb = img.convert("RGB").copy()
            thumb.thumbnail((300, 300))
            ph = ImageTk.PhotoImage(thumb)
            self._preview_imgs.append(ph)
            lbl.config(image=ph, text=cap, compound="top")

    def _preview(self):
        from tkinter import messagebox
        path = self.in_var.get().strip()
        if not path or not os.path.exists(path):
            messagebox.showerror(self.t("err"), self.t("err_input")); return
        if os.path.isdir(path):
            imgs = list(iter_images(path))
            if not imgs:
                messagebox.showerror(self.t("err"), self.t("err_input")); return
            path = imgs[0]
        src, dst = self.src_var.get(), self.dst_var.get()
        if src == dst:
            messagebox.showwarning(self.t("warn"), self.t("err_same")); return
        img = Image.open(path)
        result, used = convert_image(img, src, dst, self.skin_var.get(),
                                     float(self.strength_var.get()))
        self._show_preview(img, result)
        self.log(f"preview: {os.path.basename(path)}  [{used}->{dst}]")

    def _convert(self):
        from tkinter import messagebox
        path = self.in_var.get().strip()
        src, dst = self.src_var.get(), self.dst_var.get()
        if not path or not os.path.exists(path):
            messagebox.showerror(self.t("err"), self.t("err_input")); return
        if src == dst:
            messagebox.showwarning(self.t("warn"), self.t("err_same")); return
        suffix = self.suffix_var.get() or f"_{dst}"
        skin_only = self.skin_var.get()
        strength = float(self.strength_var.get())
        out = self.out_var.get().strip()
        try:
            if os.path.isdir(path):
                out_dir = out or (path.rstrip("/\\") + "_converted")
                run_batch(path, out_dir, src, dst, suffix, skin_only, strength, log=self.log)
            else:
                stem, ext = os.path.splitext(path)
                if out:
                    name = os.path.basename(stem) + suffix + ext
                    out_path = os.path.join(out, name)
                else:
                    out_path = stem + suffix + ext
                convert_file(path, out_path, src, dst, skin_only, strength, self.log)
                try:
                    self._show_preview(Image.open(path), Image.open(out_path))
                except Exception:
                    pass
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(self.t("err"), str(exc)); return
        if dst in APPROX_TONES or src in APPROX_TONES:
            self.log(self.t("approx_note"))
        self.log(self.t("done"))


def main():
    # CLI / self-test if any args were given.
    if len(sys.argv) > 1:
        sys.exit(run_cli(sys.argv[1:]))
    if gui_available():
        import tkinter as tk
        root = tk.Tk()
        App(root)
        root.mainloop()
    else:
        sys.exit(run_menu())


if __name__ == "__main__":
    main()
