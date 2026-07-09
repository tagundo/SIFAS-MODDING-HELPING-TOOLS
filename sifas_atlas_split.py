#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sifas_atlas_split.py — split a MERGED SIFAS model back into its parts
(atlas texture + rim texture + meshes), by grid: 2x1 / 1x2 / 2x2 / ...

The opposite of lower_body_swap.py / sifas_fbx_combine.py: those pack two
models into ONE bundle whose _MainTex/_RimlightTex is a side-by-side atlas and
whose UVs live in atlas halves. This tool takes such a merged bundle and a grid
like "2x1" (columns x rows of the atlas) and writes ONE BUNDLE PER CELL:

    * every mesh on the body material is cut by UV cell (each triangle goes to
      the cell its UV centre lies in) and its UVs are mapped back to 0..1
    * the _MainTex and _RimlightTex atlases are cropped to that cell and
      injected (RGBA32 + mipmaps), and also saved as PNGs
    * everything else (skeleton, physics, face/hair with their own textures)
      is left untouched in every output

Grid = COLUMNS x ROWS of the texture as you see it in an image editor:
"2x1" = left | right (what the merge tools produce), "1x2" = top / bottom,
"2x2" = four quadrants. Cells that contain no triangles are skipped.

Gutter: lower_body_swap.py and sifas_fbx_combine.py leave a small safety gap
(4 px of a nominal 2048-wide atlas) between the halves. By default the tool
looks at where the UVs stop inside each cell and AUTO-DETECTS that gap, so
their merges invert exactly (UVs come back to a full 0..1 and the cell
texture is the exact content rectangle). Pass --gutter N to force a value:
0 treats the atlas as a plain even grid — always safe for any atlas
(sampling stays pixel-identical), the recovered UVs just stop ~0.4% short of
the edge.

  python3 sifas_atlas_split.py --in merged.unity --grid 2x1

Runs as a window (tkinter), a text menu, or a command line. English / 한국어 /
日本語 (see SIFAS_LANG). Needs sifas_fbx.py and sifas_fbx_combine.py in the
same folder. Verified on Unity 2018.4 uncompressed SIFAS bundles.

  pip install UnityPy Pillow numpy
"""
import os, re, sys, json, math, time, argparse, traceback

# --------------------------------------------------------------------------- #
#  engines: sifas_fbx (vertex codec) + sifas_fbx_combine (model reader)        #
# --------------------------------------------------------------------------- #
def _load_engine():
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    try:
        import sifas_fbx
        import sifas_fbx_combine
    except ImportError:
        raise SystemExit(
            "sifas_atlas_split.py needs sifas_fbx.py and sifas_fbx_combine.py "
            "in the same folder (it reuses their bundle/vertex code).")
    return sifas_fbx, sifas_fbx_combine

# --------------------------------------------------------------------------- #
#  i18n  (shared with the other tools via ~/.config/sifas_modding_tools)       #
# --------------------------------------------------------------------------- #
_LANG_NAMES = (("en", "English"), ("ko", "한국어"), ("ja", "日本語"))

def _config_path():
    base = os.environ.get("XDG_CONFIG_HOME")
    if not base:
        if os.name == "nt":
            base = os.environ.get("APPDATA", os.path.expanduser("~"))
        else:
            base = os.path.expanduser("~/.config")
    return os.path.join(base, "sifas_modding_tools", "config.json")

class _LangStore:
    def __init__(self):
        self.lang = "en"
        env = os.environ.get("SIFAS_LANG")
        if env in dict(_LANG_NAMES):
            self.lang = env
        else:
            try:
                with open(_config_path(), encoding="utf-8") as f:
                    self.lang = json.load(f).get("lang", "en")
            except Exception:
                pass
    def set(self, lang):
        self.lang = lang
        try:
            p = _config_path(); os.makedirs(os.path.dirname(p), exist_ok=True)
            data = {}
            if os.path.exists(p):
                with open(p, encoding="utf-8") as f: data = json.load(f)
            data["lang"] = lang
            with open(p, "w", encoding="utf-8") as f: json.dump(data, f)
        except Exception:
            pass

_LANG = _LangStore()

_TR = {
 "ko": {
  "SIFAS Atlas Split": "SIFAS 아틀라스 분리",
  "Browse…": "찾아보기…",
  "Merged bundle:": "병합된 번들:",
  "Grid (columns x rows):": "그리드 (가로 x 세로):",
  "Output folder (blank=auto):": "출력 폴더 (빈칸=자동):",
  "Gutter px (0=plain grid):": "거터 px (0=균등 그리드):",
  "Meshes:": "메시:",
  "body material only": "바디 재질만",
  "all meshes": "모든 메시",
  "custom names…": "이름 직접 입력…",
  "Custom names (comma):": "메시 이름 (쉼표 구분):",
  "Scan meshes": "메시 스캔",
  "Generate mipmaps": "밉맵 생성",
  "Dry run (no write)": "미리보기만 (저장 안 함)",
  "Run": "실행",
  "Language:": "언어:",
  "Done.": "완료.",
  "Working…": "작업 중…",
  "Pick a merged bundle first.": "먼저 병합된 번들을 선택하세요.",
  "Saved: %s": "저장됨: %s",
  "ERROR: %s": "오류: %s",
 },
 "ja": {
  "SIFAS Atlas Split": "SIFAS アトラス分離",
  "Browse…": "参照…",
  "Merged bundle:": "結合済みバンドル:",
  "Grid (columns x rows):": "グリッド (横 x 縦):",
  "Output folder (blank=auto):": "出力フォルダ (空欄=自動):",
  "Gutter px (0=plain grid):": "ガター px (0=等分グリッド):",
  "Meshes:": "メッシュ:",
  "body material only": "ボディ材質のみ",
  "all meshes": "全メッシュ",
  "custom names…": "名前を直接入力…",
  "Custom names (comma):": "メッシュ名 (カンマ区切り):",
  "Scan meshes": "メッシュをスキャン",
  "Generate mipmaps": "ミップマップ生成",
  "Dry run (no write)": "ドライラン (保存しない)",
  "Run": "実行",
  "Language:": "言語:",
  "Done.": "完了。",
  "Working…": "処理中…",
  "Pick a merged bundle first.": "先に結合済みバンドルを選択してください。",
  "Saved: %s": "保存しました: %s",
  "ERROR: %s": "エラー: %s",
 },
}

def _tr(text):
    return _TR.get(_LANG.lang, {}).get(text, text)

# --------------------------------------------------------------------------- #
#  Grid geometry.  The gutter fraction uses the SAME nominal-2048 convention   #
#  as lower_body_swap.py / sifas_fbx_combine.py, generalised to N cells per    #
#  axis: content width cw = (1 - 2g*(N-1))/N, cell k starts at k*(cw + 2g).    #
#  With g = 0 this reduces to the plain even grid (k/N .. (k+1)/N).            #
# --------------------------------------------------------------------------- #
NOMINAL_W = 2048

def parse_grid(text):
    m = re.fullmatch(r"\s*(\d+)\s*[xX×]\s*(\d+)\s*", text or "")
    if not m:
        raise ValueError("grid must look like 2x1 / 1x2 / 2x2 (columns x rows), got %r" % text)
    C, R = int(m.group(1)), int(m.group(2))
    if not (1 <= C <= 8 and 1 <= R <= 8) or C * R < 2:
        raise ValueError("grid %dx%d out of range (1..8 per axis, at least 2 cells)" % (C, R))
    return C, R

def _axis(n, g):
    """(content_width, start_of_cell_k) along one axis with n cells."""
    cw = (1.0 - 2.0 * g * (n - 1)) / n
    return cw, (lambda k: k * (cw + 2.0 * g))

def part_names(C, R):
    """Cell display names in image reading order (top-left first).
    Returns {(col, image_row): name}."""
    if R == 1 and C == 2:
        cols = ["left", "right"]
    elif R == 1 and C == 3:
        cols = ["left", "center", "right"]
    else:
        cols = None
    if C == 1 and R == 2:
        rows = ["top", "bottom"]
    else:
        rows = None
    out = {}
    for j in range(R):
        for i in range(C):
            if C == 2 and R == 2:
                out[(i, j)] = ("top" if j == 0 else "bottom") + ("left" if i == 0 else "right")
            elif R == 1 and cols:
                out[(i, j)] = cols[i]
            elif C == 1 and rows:
                out[(i, j)] = rows[j]
            else:
                out[(i, j)] = "c%dr%d" % (i + 1, j + 1)
    return out

# --------------------------------------------------------------------------- #
#  Mesh subsetting (vertex codec shared from sifas_fbx)                        #
# --------------------------------------------------------------------------- #
def _read_mesh_arrays(F, mesh):
    vc, chans, stride, start, _ = F.stream_layout(mesh)
    u8 = F.np.frombuffer(bytes(mesh["m_VertexData"]["m_DataSize"]), F.np.uint8)
    uv = F.read_attr(u8, chans, F.CH_UV0, stride, start, vc)
    tris = F.read_indices(mesh).reshape(-1, 3)
    return uv, tris

def _subset_mesh(F, mesh, keep_tris, uv_fn, log, name):
    """Rewrite `mesh` (typetree, in place) so it contains only `keep_tris`
    (indices into the ORIGINAL vertex list), with uv_fn applied to UV0.
    Empty keep -> one invisible zero-area triangle on vertex 0."""
    np = F.np
    vc, chans, stride, start, _ = F.stream_layout(mesh)
    u8 = np.frombuffer(bytes(mesh["m_VertexData"]["m_DataSize"]), np.uint8)
    if len(keep_tris) == 0:
        used = np.array([0], np.int64)
        new_tris = np.zeros((1, 3), np.int64)
        log("  %s: empty in this cell -> collapsed to an invisible point" % name)
    else:
        used = np.unique(keep_tris)
        remap = np.full(vc, -1, np.int64)
        remap[used] = np.arange(len(used))
        new_tris = remap[keep_tris]
    new_vc = int(len(used))
    order = sorted({c["stream"] for c in chans if c.get("dimension", 0)})
    blocks = []
    for s in order:
        blk = u8[start[s]:start[s] + vc * stride[s]].reshape(vc, stride[s])
        nb = blk[used].tobytes()
        blocks.append(nb + b"\x00" * ((-len(nb)) % 16))
    mesh["m_VertexData"]["m_VertexCount"] = new_vc
    mesh["m_VertexData"]["m_DataSize"] = b"".join(blocks)
    vc2, chans2, stride2, start2, _ = F.stream_layout(mesh)
    buf = bytearray(mesh["m_VertexData"]["m_DataSize"])
    u82 = np.frombuffer(buf, np.uint8)
    uv = F.read_attr(u82, chans2, F.CH_UV0, stride2, start2, vc2)
    if uv is not None and len(keep_tris):
        uv2 = uv.copy()
        uv2[:, 0], uv2[:, 1] = uv_fn(uv[:, 0], uv[:, 1])
        F.write_attr(u82, uv2, chans2, F.CH_UV0, stride2, start2, vc2)
        mesh["m_VertexData"]["m_DataSize"] = bytes(buf)
    pos = F.read_attr(u82, chans2, F.CH_POS, stride2, start2, vc2)
    idx = new_tris.reshape(-1)
    fmt = mesh.get("m_IndexFormat", 0)
    if new_vc > 65535 and fmt == 0:
        fmt = 1
        mesh["m_IndexFormat"] = 1
    mesh["m_IndexBuffer"] = idx.astype("<u2" if fmt == 0 else "<u4").tobytes()
    sm = mesh["m_SubMeshes"][0]
    sm["firstByte"] = 0; sm["indexCount"] = int(idx.size)
    sm["firstVertex"] = 0; sm["vertexCount"] = new_vc; sm["baseVertex"] = 0
    mn, mx = pos.min(0), pos.max(0)
    ctr, ext = (mn + mx) / 2, (mx - mn) / 2
    aabb = {"m_Center": {"x": float(ctr[0]), "y": float(ctr[1]), "z": float(ctr[2])},
            "m_Extent": {"x": float(ext[0]), "y": float(ext[1]), "z": float(ext[2])}}
    mesh["m_LocalAABB"] = aabb
    if isinstance(sm.get("localAABB"), dict):
        sm["localAABB"] = dict(aabb)
    mesh["m_SubMeshes"] = [sm]
    return new_vc, len(new_tris) if len(keep_tris) else 0

def scan_model(in_path, log=print):
    """List the bundle's skinned meshes (name / verts / bones / texture, with
    the body-material ones marked) — what to type into the custom-names box."""
    _F, CB = _load_engine()
    return CB.scan_model(in_path, log)

# --------------------------------------------------------------------------- #
#  Core split                                                                  #
# --------------------------------------------------------------------------- #
def split_model(in_path, grid, out_dir=None, gutter_px="auto", meshes="body",
                mipmaps=True, dry_run=False, log=print):
    t0 = time.time()
    log("[info] loading engine (a first run may auto-install numpy/UnityPy)…")
    F, CB = _load_engine()
    np = F.np
    from UnityPy.enums import TextureFormat

    C, R = parse_grid(grid) if isinstance(grid, str) else grid
    names = part_names(C, R)
    if out_dir is None:
        out_dir = os.path.splitext(in_path)[0] + "_split"

    # ---- pass 1: read the merged model, assign every triangle to a cell ---- #
    log("[info] reading %s…" % os.path.basename(in_path))
    side = CB._Side(F, in_path, "merged")
    sel = CB._select_meshes(meshes, side)
    log("[info] splitting %s into a %dx%d grid"
        % (", ".join(r.name for r in sel), C, R))

    keep = {}          # mesh path_id -> {(col, imgrow): tris array}
    counts = {}        # (col, imgrow) -> total tris
    max_frac_u = max_frac_v = 0.0
    crossing = 0
    for rec in sel:
        uv, tris = _read_mesh_arrays(F, rec.mesh)
        if uv is None:
            log("[warn] %s has no UV0 — left untouched" % rec.name)
            continue
        cu = uv[tris].mean(1)                                # tri centroid UV
        col = np.clip(np.floor(cu[:, 0] * C).astype(int), 0, C - 1)
        kv = np.clip(np.floor(cu[:, 1] * R).astype(int), 0, R - 1)   # v cell, bottom-up
        vcol = np.clip(np.floor(uv[tris][:, :, 0] * C).astype(int), 0, C - 1)
        vkv = np.clip(np.floor(uv[tris][:, :, 1] * R).astype(int), 0, R - 1)
        crossing += int(((vcol != col[:, None]) | (vkv != kv[:, None])).any(1).sum())
        if C > 1:
            fr = uv[:, 0] * C - np.floor(uv[:, 0] * C)
            fr = fr[(uv[:, 0] > 1e-6) & (uv[:, 0] < 1 - 1e-6)]
            if len(fr):
                max_frac_u = max(max_frac_u, float(fr.max()))
        if R > 1:
            fr = uv[:, 1] * R - np.floor(uv[:, 1] * R)
            fr = fr[(uv[:, 1] > 1e-6) & (uv[:, 1] < 1 - 1e-6)]
            if len(fr):
                max_frac_v = max(max_frac_v, float(fr.max()))
        d = keep.setdefault(rec.smr.path_id, {})
        for j in range(R):
            for i in range(C):
                m = (col == i) & (kv == R - 1 - j)
                d[(i, j)] = tris[m]
                counts[(i, j)] = counts.get((i, j), 0) + int(m.sum())
    if crossing:
        log("[warn] %d triangle(s) span more than one cell — each goes to its "
            "centre's cell; their texture may look stretched there" % crossing)

    # ---- resolve the gutter (auto-detect from where the UVs stop) ---------- #
    # Window note: a 4 px gutter puts the UV edge at 99.61% of the cell; UVs of
    # an UN-guttered mesh often stop at 99.8-100%. The upper bound 0.997 keeps
    # those from being mistaken for a tiny gutter (>=3 px is still detected).
    def _detect(max_frac):
        if 0.985 <= max_frac <= 0.997:
            return int(round((1.0 - max_frac) * NOMINAL_W / 2.0))
        return 0
    if gutter_px in (None, "", "auto"):
        gu_px, gv_px = _detect(max_frac_u), _detect(max_frac_v)
        log("[auto] gutter detected: %d px%s"
            % (gu_px, (" (u) / %d px (v)" % gv_px) if R > 1 and C > 1 else
               ("" if C > 1 else " (v)")))
    else:
        gu_px = gv_px = int(gutter_px)
        log("[info] gutter forced to %d px" % gu_px)
        if gu_px == 0 and 0.985 <= max(max_frac_u, max_frac_v) <= 0.997:
            hint = _detect(max(max_frac_u, max_frac_v))
            log("[hint] the UVs stop at %.2f%% of each cell — this looks like an "
                "atlas made with a %d px gutter (lower_body_swap / "
                "sifas_fbx_combine). Re-run with --gutter %d (or auto) to recover "
                "exact 0..1 UVs." % (max(max_frac_u, max_frac_v) * 100, hint, hint))
    gU, gV = gu_px / NOMINAL_W, gv_px / NOMINAL_W
    ucw, ustart = _axis(C, gU)
    vcw, vstart = _axis(R, gV)

    for (i, j), n in sorted(counts.items(), key=lambda kv_: (kv_[0][1], kv_[0][0])):
        log("  cell %-11s: %d tris" % (names[(i, j)], n))
    live = [(i, j) for (i, j), n in counts.items() if n > 0]
    if not live:
        raise ValueError("no triangles found in any grid cell — wrong grid? wrong meshes?")
    skipped = [names[c] for c in sorted(set(counts) - set(live), key=lambda c: (c[1], c[0]))]
    if skipped:
        log("[info] empty cell(s) skipped: %s" % ", ".join(skipped))
    if dry_run:
        log("  [dry run] would write %d bundle(s) + textures to %s"
            % (len(live), out_dir))
        return []

    # ---- cell texture crops (from pass-1 images) --------------------------- #
    def cell_image(img, i, j):
        W, H = img.width, img.height
        if gU > 0 or gV > 0:
            u0 = ustart(i); v0 = vstart(R - 1 - j)
            x0 = int(round(u0 * W)); x1 = int(round((u0 + ucw) * W))
            y0 = int(round((1.0 - v0 - vcw) * H)); y1 = int(round((1.0 - v0) * H))
            return img.crop((x0, y0, x1, y1)).resize((W // C, H // R))
        return img.crop((i * W // C, j * H // R, (i + 1) * W // C, (j + 1) * H // R))

    tex_pids = [p for p in (side.body.main_pid, side.body.rim_pid) if p]
    log("[info] decoding %d texture(s)…" % len(tex_pids))
    tex_imgs = {p: side.tex_image(p) for p in tex_pids}
    tex_names = {p: side.tex_name(p) for p in tex_pids}

    def uv_fn(i, j):
        u0 = ustart(i); v0 = vstart(R - 1 - j)
        return lambda u, v: ((u - u0) / ucw, (v - v0) / vcw)

    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.basename(in_path)
    root, ext = os.path.splitext(stem)
    outs = []
    for (i, j) in sorted(live, key=lambda c: (c[1], c[0])):
        part = names[(i, j)]
        log("[info] writing part '%s'…" % part)
        # fresh load per cell: same battle-tested mutate-once-save-once flow
        # as the other tools
        cell = CB._Side(F, in_path, part)
        csel = {r.smr.path_id: r for r in CB._select_meshes(meshes, cell)}
        fn = uv_fn(i, j)
        for pid, tris_by_cell in keep.items():
            rec = csel.get(pid)
            if rec is None:
                continue
            nv, nt = _subset_mesh(F, rec.mesh, tris_by_cell[(i, j)], fn, log, rec.name)
            rec.mesh_obj.save_typetree(rec.mesh)
            if nt:
                log("  %-11s %s: %d verts, %d tris" % (part, rec.name, nv, nt))
        for p in tex_pids:
            img = cell_image(tex_imgs[p], i, j)
            tex = cell.uid[p].read()
            mc = int(math.floor(math.log2(max(img.size)))) + 1 if mipmaps else 1
            tex.set_image(img, target_format=TextureFormat.RGBA32, mipmap_count=mc)
            tex.save()
            png = os.path.join(out_dir, "%s_%s.png" % (tex_names[p], part))
            img.save(png)
        out_path = os.path.join(out_dir, "%s_%s%s" % (root, part, ext))
        with open(out_path, "wb") as f:
            f.write(cell.env.file.save(packer="original"))
        log(_tr("Saved: %s") % out_path)
        outs.append(out_path)
    log("[done] %d part(s) in %.1fs -> %s" % (len(outs), time.time() - t0, out_dir))
    return outs

# --------------------------------------------------------------------------- #
#  CLI                                                                         #
# --------------------------------------------------------------------------- #
def main_cli(argv):
    p = argparse.ArgumentParser(
        description="Split a merged SIFAS model (atlas texture + rim + meshes) "
                    "back into per-cell bundles by a COLUMNSxROWS grid.",
        epilog="examples:  --in merged.unity --grid 2x1 --gutter 4   (undo "
               "lower_body_swap / sifas_fbx_combine)   ·   --grid 2x2 for a "
               "four-part atlas")
    p.add_argument("--in", dest="infile", required=True, help="merged bundle to split")
    p.add_argument("--scan", action="store_true",
                   help="just list the bundle's meshes (names / verts / bones / "
                        "textures) and exit — use it to fill --meshes")
    p.add_argument("--grid",
                   help="atlas grid: columns x rows, e.g. 2x1 (left|right), "
                        "1x2 (top/bottom), 2x2")
    p.add_argument("--out", default=None,
                   help="output folder (default: <input>_split)")
    p.add_argument("--gutter", default="auto",
                   help="gutter px (nominal 2048-wide) the atlas was built with. "
                        "Default 'auto' detects it from the UVs (4 for "
                        "lower_body_swap / sifas_fbx_combine merges); 0 = plain "
                        "even grid")
    p.add_argument("--meshes", default="body", metavar="body|all|A,B",
                   help="which meshes to split (default body: every mesh on "
                        "the body material)")
    p.add_argument("--no-mipmaps", action="store_true",
                   help="no mipmaps in the injected cell textures")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args(argv)
    if a.scan:
        scan_model(a.infile)
        return
    if not a.grid:
        p.error("--grid is required (or use --scan to list the meshes)")
    gut = a.gutter if str(a.gutter).strip().lower() == "auto" else int(a.gutter)
    split_model(a.infile, a.grid, out_dir=a.out, gutter_px=gut,
                meshes=a.meshes, mipmaps=not a.no_mipmaps, dry_run=a.dry_run)

# --------------------------------------------------------------------------- #
#  Text menu (no display / Termux)                                            #
# --------------------------------------------------------------------------- #
def main_menu():
    print("=== %s ===" % _tr("SIFAS Atlas Split"))
    src = input(_tr("Merged bundle:") + " ").strip()
    grid = input(_tr("Grid (columns x rows):") + " [2x1] ").strip() or "2x1"
    gut = input(_tr("Gutter px (0=plain grid):") + " [auto] ").strip().lower()
    gut = "auto" if gut in ("", "auto") else int(gut)
    out = input(_tr("Output folder (blank=auto):") + " ").strip() or None
    split_model(src, grid, out_dir=out, gutter_px=gut)

# --------------------------------------------------------------------------- #
#  GUI (tkinter)                                                               #
# --------------------------------------------------------------------------- #
def main_gui():
    import threading, queue
    import tkinter as tk
    from tkinter import ttk, filedialog
    root = tk.Tk()
    root.title(_tr("SIFAS Atlas Split"))
    q = queue.Queue()

    def row(r, label):
        ttk.Label(root, text=_tr(label)).grid(row=r, column=0, sticky="w", padx=6, pady=3)
        e = ttk.Entry(root, width=52); e.grid(row=r, column=1, padx=4, pady=3)
        return e

    in_e = row(0, "Merged bundle:")
    out_e = row(1, "Output folder (blank=auto):")

    def browse(entry, folder=False):
        path = filedialog.askdirectory() if folder else filedialog.askopenfilename()
        if path:
            entry.delete(0, "end"); entry.insert(0, path)
    ttk.Button(root, text=_tr("Browse…"), command=lambda: browse(in_e)).grid(row=0, column=2, padx=4)
    ttk.Button(root, text=_tr("Browse…"), command=lambda: browse(out_e, True)).grid(row=1, column=2, padx=4)

    grow = ttk.Frame(root); grow.grid(row=2, column=1, columnspan=2, sticky="w")
    ttk.Label(grow, text=_tr("Grid (columns x rows):")).pack(side="left")
    grid_box = ttk.Combobox(grow, width=8, values=["2x1", "1x2", "2x2", "3x1", "2x3"])
    grid_box.set("2x1"); grid_box.pack(side="left", padx=4)
    ttk.Label(grow, text=_tr("Gutter px (0=plain grid):")).pack(side="left", padx=(10, 0))
    gut_e = ttk.Entry(grow, width=5); gut_e.insert(0, "auto"); gut_e.pack(side="left", padx=2)

    mrow = ttk.Frame(root); mrow.grid(row=3, column=1, columnspan=2, sticky="w")
    MESH_OPTS = [("body", "body material only"), ("all", "all meshes"), ("custom", "custom names…")]
    ttk.Label(mrow, text=_tr("Meshes:")).pack(side="left")
    mesh_box = ttk.Combobox(mrow, state="readonly", width=18,
                            values=[_tr(lbl) for _k, lbl in MESH_OPTS])
    mesh_box.current(0); mesh_box.pack(side="left", padx=4)
    mesh_custom = ttk.Entry(mrow, width=22); mesh_custom.pack(side="left", padx=2)

    def scan_click():
        src = in_e.get().strip()
        if not src:
            q.put(_tr("Pick a merged bundle first.")); return
        def sw():
            try:
                scan_model(src, log=put)
            except BaseException as e:
                put(_tr("ERROR: %s") % e)
        threading.Thread(target=sw, daemon=True).start()
    ttk.Button(mrow, text=_tr("Scan meshes"), command=scan_click).pack(side="left", padx=(10, 0))

    mip_var = tk.BooleanVar(value=True)
    dry_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(root, text=_tr("Generate mipmaps"), variable=mip_var).grid(row=4, column=1, sticky="w")
    ttk.Checkbutton(root, text=_tr("Dry run (no write)"), variable=dry_var).grid(row=5, column=1, sticky="w")

    log = tk.Text(root, height=14, width=76); log.grid(row=7, column=0, columnspan=3, padx=6, pady=6)
    def put(msg): q.put(str(msg))

    def work():
        try:
            src = in_e.get().strip()
            if not src:
                put(_tr("Pick a merged bundle first.")); return
            key = MESH_OPTS[mesh_box.current()][0]
            if key == "custom":
                key = mesh_custom.get().strip() or "body"
            gut = gut_e.get().strip().lower()
            gut = "auto" if gut in ("", "auto") else int(gut)
            put(_tr("Working…"))
            split_model(src, grid_box.get().strip() or "2x1",
                        out_dir=out_e.get().strip() or None,
                        gutter_px=gut,
                        meshes=key, mipmaps=mip_var.get(),
                        dry_run=dry_var.get(), log=put)
            put(_tr("Done."))
        except BaseException as e:            # incl. SystemExit from _load_engine —
            put(_tr("ERROR: %s") % e)         # a silent thread death looked like an
            put(traceback.format_exc())       # endless "Working…"

    def run():
        threading.Thread(target=work, daemon=True).start()
    ttk.Button(root, text=_tr("Run"), command=run).grid(row=6, column=1, pady=4)

    ttk.Label(root, text=_tr("Language:")).grid(row=8, column=0, sticky="w", padx=6)
    lang_var = tk.StringVar(value=dict(_LANG_NAMES)[_LANG.lang])
    def on_lang(_e=None):
        for code, name in _LANG_NAMES:
            if name == lang_var.get():
                _LANG.set(code)
        root.destroy(); main_gui()
    lb = ttk.Combobox(root, textvariable=lang_var, state="readonly",
                      values=[n for _c, n in _LANG_NAMES]); lb.grid(row=8, column=1, sticky="w")
    lb.bind("<<ComboboxSelected>>", on_lang)

    def pump():
        try:
            while True:
                log.insert("end", q.get_nowait() + "\n"); log.see("end")
        except queue.Empty:
            pass
        root.after(120, pump)
    pump()
    root.mainloop()

# --------------------------------------------------------------------------- #
def main():
    if len(sys.argv) > 1:
        main_cli(sys.argv[1:]); return
    try:
        import tkinter  # noqa
        if os.environ.get("DISPLAY") or os.name == "nt" or sys.platform == "darwin":
            main_gui(); return
    except Exception:
        pass
    main_menu()

if __name__ == "__main__":
    main()
