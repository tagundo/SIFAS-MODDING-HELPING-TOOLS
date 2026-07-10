#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sifas_fbx_combine.py — combine TWO SIFAS models into ONE Blender-ready FBX
(with automatic texture + rim atlas)

lower_body_swap.py grafts a donor's lower body onto a target automatically,
inside the bundle. This tool does the SAME preparation — two models, one merged
texture atlas (left half = base, right half = donor), UVs remapped — but instead
of cutting the meshes itself it writes ONE COMBINED FBX and lets YOU do the
cutting/joining in Blender. Use it when the automatic band cut isn't enough
(kitbashing costume parts, custom seams, sculpt fixes...).

What one run produces
    1. <out>.fbx        — both models in one file, sharing ONE skeleton
                          (bones matched by name; donor-only bones are added).
                          Donor meshes/materials are renamed with a suffix
                          ("Body" -> "Body_D") so nothing collides.
    2. <out>_tex/       — the merged _MainTex atlas (and _RimlightTex atlas)
                          as PNG, plus the plain textures of every other
                          included mesh, so the FBX opens textured in Blender.
    3. <out>_atlas.unity — the BASE bundle with the atlas textures injected and
                          its body UVs moved to the left half. This is the
                          bundle you re-import the edited FBX into. (It is
                          already valid in-game, it just wastes the right half
                          until donor parts are imported.)

Workflow
    python3 sifas_fbx_combine.py --base A.unity --donor B.unity --out comb.fbx
    -> open comb.fbx in Blender, delete/keep/join parts (donor pieces you keep
       must end up in a mesh OBJECT whose name matches a base mesh, e.g. join
       "Body_D" into "Body" with Ctrl+J), export as binary FBX
    -> python3 sifas_fbx.py import --fbx edited.fbx --bundle comb_atlas.unity \
                                   --out final.unity

Because every SIFAS model of a character shares one skeleton and rest pose,
donor meshes bind to the base skeleton by bone NAME. Donor bones that do not
exist in the base bundle (e.g. another costume's skirt physics) are still put
in the FBX so Blender shows correct weights — but the base bundle cannot
receive weights for them at re-import. The tool prints exactly which bones
those are; use --reskin-missing to re-target such weights onto the nearest
ancestor bone the base does have (like lower_body_swap does), or keep them and
re-weight in Blender, or add the bones to the base first with
costume_transplant.py.

Runs as a window (tkinter), a text menu, or a command line. English / 한국어 /
日本語 (see SIFAS_LANG). Needs sifas_fbx.py in the same folder (it reuses its
verified FBX writer). Verified on Unity 2018.4 uncompressed SIFAS bundles.

  pip install UnityPy Pillow numpy
"""
import os, sys, json, math, time, argparse, traceback

# --------------------------------------------------------------------------- #
#  sifas_fbx.py is the FBX engine (writer + vertex codec); require it nearby   #
# --------------------------------------------------------------------------- #
def _load_engine():
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    try:
        import sifas_fbx
    except ImportError:
        raise SystemExit(
            "sifas_fbx_combine.py needs sifas_fbx.py in the same folder "
            "(it reuses its FBX writer). Get both files from the repo.")
    return sifas_fbx

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
  "SIFAS FBX Combine": "SIFAS FBX 결합",
  "Browse…": "찾아보기…",
  "Base model (re-import target):": "베이스 모델 (재임포트 대상):",
  "Donor model (parts to bring):": "도너 모델 (가져올 부분):",
  "Output FBX:": "출력 FBX:",
  "Texture folder (blank=auto):": "텍스처 폴더 (빈칸=자동):",
  "Atlas bundle out (blank=auto):": "아틀라스 번들 출력 (빈칸=자동):",
  "Donor meshes:": "도너 메시:",
  "Base meshes:": "베이스 메시:",
  "body material only": "바디 재질만",
  "all meshes": "모든 메시",
  "custom names…": "이름 직접 입력…",
  "Custom names (comma):": "메시 이름 (쉼표 구분):",
  "Scan meshes": "메시 스캔",
  "Donor name suffix:": "도너 이름 접미사:",
  "Merge rim map too": "Rim맵도 병합",
  "Generate mipmaps": "밉맵 생성",
  "Re-skin weights on bones missing from base": "베이스에 없는 본의 가중치 재배치",
  "Skip atlas bundle": "아틀라스 번들 생략",
  "Dry run (no write)": "미리보기만 (저장 안 함)",
  "Run": "실행",
  "Language:": "언어:",
  "Done.": "완료.",
  "Working…": "작업 중…",
  "Pick a base and a donor first.": "먼저 베이스와 도너를 선택하세요.",
  "Saved: %s": "저장됨: %s",
  "ERROR: %s": "오류: %s",
  "no skinned mesh found in %s": "%s 에서 스킨 메시를 찾지 못했습니다",
 },
 "ja": {
  "SIFAS FBX Combine": "SIFAS FBX 結合",
  "Browse…": "参照…",
  "Base model (re-import target):": "ベースモデル (再インポート先):",
  "Donor model (parts to bring):": "ドナーモデル (持ち込むパーツ):",
  "Output FBX:": "出力FBX:",
  "Texture folder (blank=auto):": "テクスチャフォルダ (空欄=自動):",
  "Atlas bundle out (blank=auto):": "アトラスバンドル出力 (空欄=自動):",
  "Donor meshes:": "ドナーメッシュ:",
  "Base meshes:": "ベースメッシュ:",
  "body material only": "ボディ材質のみ",
  "all meshes": "全メッシュ",
  "custom names…": "名前を直接入力…",
  "Custom names (comma):": "メッシュ名 (カンマ区切り):",
  "Scan meshes": "メッシュをスキャン",
  "Donor name suffix:": "ドナー名の接尾辞:",
  "Merge rim map too": "リムマップも統合",
  "Generate mipmaps": "ミップマップ生成",
  "Re-skin weights on bones missing from base": "ベースに無いボーンのウェイトを再配置",
  "Skip atlas bundle": "アトラスバンドルを省略",
  "Dry run (no write)": "ドライラン (保存しない)",
  "Run": "実行",
  "Language:": "言語:",
  "Done.": "完了。",
  "Working…": "処理中…",
  "Pick a base and a donor first.": "先にベースとドナーを選択してください。",
  "Saved: %s": "保存しました: %s",
  "ERROR: %s": "エラー: %s",
  "no skinned mesh found in %s": "%s にスキンメッシュが見つかりません",
 },
}

def _tr(text):
    return _TR.get(_LANG.lang, {}).get(text, text)

# --------------------------------------------------------------------------- #
#  Atlas geometry — identical convention to lower_body_swap.py                 #
#  (UV fractions use a NOMINAL 2048-wide atlas so both the _MainTex and the    #
#   smaller _RimlightTex atlas share one UV set; the pixel rects below match)  #
# --------------------------------------------------------------------------- #
NOMINAL_W = 2048

def _uv_halves(gutter_px):
    g = gutter_px / NOMINAL_W
    def uL(u): return u * (0.5 - g)
    def uR(u): return 0.5 + g + u * (0.5 - g)
    return g, uL, uR

def _pow2(x):
    p = 1
    while p < x:
        p <<= 1
    return p

def _combine_images(base_img, donor_img, g):
    """Side-by-side atlas: base LEFT, donor RIGHT. Size-adaptive (each half as
    big as the larger source, snapped to power-of-two), with the centre gutter
    filled by edge replication so bilinear/mip sampling can't bleed across."""
    from PIL import Image
    side = _pow2(max(base_img.width, donor_img.width))
    H = _pow2(max(base_img.height, donor_img.height))
    W = side * 2
    fw = max(1, int(round((0.5 - g) * W)))       # base (left) content width
    ds = int(round((0.5 + g) * W))               # donor-half start x (== uR(0)*W)
    dw = W - ds                                  # donor (right) content width
    ti = base_img.resize((fw, H))
    di = donor_img.resize((dw, H))
    c = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    c.paste(ti, (0, 0)); c.paste(di, (ds, 0))
    if ds > fw:
        right_col = ti.crop((fw - 1, 0, fw, H))
        left_col = di.crop((0, 0, 1, H))
        for x in range(fw, ds):
            c.paste(right_col if (x - fw) < (ds - fw) // 2 else left_col, (x, 0))
    return c

# --------------------------------------------------------------------------- #
#  One model side (base or donor): env + skeleton + per-renderer records       #
# --------------------------------------------------------------------------- #
class _Side:
    def __init__(self, F, path, label):
        self.F = F; self.path = path; self.label = label
        self.env = F.UnityPy.load(path)
        (self.local, self.world, self.parent,
         self.name2pid, self.uid) = F.bundle_skeleton(self.env)
        body_smr = F.body_smr(self.env)
        if body_smr is None:
            raise ValueError(_tr("no skinned mesh found in %s") % os.path.basename(path))
        self.smrs = []
        for o in self.env.objects:
            if o.type.name != "SkinnedMeshRenderer":
                continue
            tt = o.read_typetree()
            mesh_obj = self.uid.get(tt.get("m_Mesh", {}).get("m_PathID"))
            if mesh_obj is None:
                continue
            mesh = mesh_obj.read_typetree()
            bones = [self._bone_name(b.get("m_PathID")) for b in tt.get("m_Bones", [])]
            main_pid = rim_pid = None; mat_name = None
            mats = tt.get("m_Materials") or []
            if mats:
                mo = self.uid.get(mats[0].get("m_PathID"))
                if mo is not None:
                    mtt = mo.read_typetree()
                    mat_name = mtt.get("m_Name")
                    for nm, envp in mtt.get("m_SavedProperties", {}).get("m_TexEnvs", []):
                        pid = envp.get("m_Texture", {}).get("m_PathID", 0)
                        if nm == "_MainTex" and pid:
                            main_pid = pid
                        elif nm == "_RimlightTex" and pid:
                            rim_pid = pid
            self.smrs.append(_Rec(o, tt, mesh_obj, mesh, mesh.get("m_Name", "mesh"),
                                  bones, mat_name, main_pid, rim_pid,
                                  o.path_id == body_smr.path_id))
        if not self.smrs:
            raise ValueError(_tr("no skinned mesh found in %s") % os.path.basename(path))
        # the body renderer's own Mesh may be missing/unreadable — fall back to
        # the most-bones readable renderer instead of dying with StopIteration
        self.body = next((r for r in self.smrs if r.is_body), None) \
            or max(self.smrs, key=lambda r: len(r.bones))

    def _bone_name(self, pid):
        o = self.uid.get(pid)
        if not o:
            return None
        t = o.read_typetree()
        g = self.uid.get(t.get("m_GameObject", {}).get("m_PathID"))
        return g.read().m_Name if g else None

    def tex_name(self, pid):
        o = self.uid.get(pid)
        return o.read().m_Name if o else None

    def tex_image(self, pid):
        o = self.uid.get(pid)
        if o is None:
            return None
        d = o.read()
        fmt = str(getattr(d, "m_TextureFormat", "") or "")
        if any(k in fmt for k in _NATIVE_DECODED):
            # Compressed formats decode through texture2ddecoder's NATIVE code,
            # which can take the whole process down (Crunch textures are known
            # to segfault it on macOS/Apple Silicon — a crash Python cannot
            # catch; it killed the GUI). Decode them in an isolated child
            # process (sifas_fbx's __decode_tex mode) instead.
            img, crashed = _decode_texture_isolated(self.path, d.m_Name)
            if img is not None:
                return img.convert("RGBA")
            if crashed or "Crunched" in fmt:
                raise RuntimeError(
                    "texture '%s' (%s): the native decoder crashed on it even "
                    "in an isolated process — a known texture2ddecoder problem "
                    "on macOS. Run this step on Windows/Linux, or re-save the "
                    "texture uncompressed first (import it once with the "
                    "texture importer)." % (d.m_Name, fmt))
            # the child could not run at all (no decoder crash) — fall through
            # to the normal in-process decode below
        return d.image.convert("RGBA")

# texture formats whose decode goes through texture2ddecoder's native library
_NATIVE_DECODED = ("Crunched", "DXT", "BC4", "BC5", "BC6", "BC7",
                   "ETC", "EAC", "ASTC", "PVRTC", "ATC")

def _decode_texture_isolated(bundle_path, tex_name, timeout=180):
    """Decode one texture to PNG in a CHILD process so a native decoder crash
    only loses that texture instead of the whole tool. Returns (Image or None,
    crashed) — crashed=True when the child died decoding (signal / timeout)."""
    import subprocess, tempfile
    from PIL import Image
    F = _load_engine()
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "tex.png")
        try:
            r = subprocess.run([sys.executable, os.path.abspath(F.__file__),
                                "__decode_tex", bundle_path, tex_name, out],
                               capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return None, True
        except Exception:
            return None, False
        if r.returncode == 0 and os.path.exists(out):
            img = Image.open(out)
            img.load()
            return img, False
        return None, r.returncode < 0

def _mesh_ok(F, mesh):
    """(True, '') when the mesh's vertex data is plain, in-bundle and non-empty
    — the only kind these tools can edit; else (False, why). Guards against
    crashes on streamed (m_StreamData), compressed or stripped meshes."""
    try:
        vc, chans, stride, start, _ = F.stream_layout(mesh)
    except Exception as ex:
        return False, "unreadable vertex layout (%s)" % ex
    if vc <= 0:
        return False, "no vertices"
    if not mesh.get("m_SubMeshes"):
        return False, "no submeshes"
    need = max((start[s] + vc * stride[s]) for s in stride) if stride else 0
    if len(bytes(mesh["m_VertexData"]["m_DataSize"])) < need:
        return False, "vertex data is external (m_StreamData) or compressed"
    return True, ""

class _Rec:
    __slots__ = ("smr", "smr_tt", "mesh_obj", "mesh", "name", "bones",
                 "mat_name", "main_pid", "rim_pid", "is_body")
    def __init__(self, smr, smr_tt, mesh_obj, mesh, name, bones,
                 mat_name, main_pid, rim_pid, is_body):
        self.smr = smr; self.smr_tt = smr_tt; self.mesh_obj = mesh_obj
        self.mesh = mesh; self.name = name; self.bones = bones
        self.mat_name = mat_name; self.main_pid = main_pid
        self.rim_pid = rim_pid; self.is_body = is_body

def scan_model(path, log=print):
    """List every skinned mesh in a bundle — name, verts, bones, texture and
    whether it sits on the BODY material — so the user knows exactly what to
    type into --base-meshes / --donor-meshes (or the tools' custom-name box)."""
    F = _load_engine()
    side = _Side(F, path, "scan")
    log("[scan] %s" % os.path.basename(path))
    for r in side.smrs:
        vc = r.mesh.get("m_VertexData", {}).get("m_VertexCount", 0)
        body = bool(side.body.main_pid) and r.main_pid == side.body.main_pid
        log("  %s %-30s %6d verts  %3d bones  tex=%s"
            % ("[body]" if body else "      ", "'%s'" % r.name, vc, len(r.bones),
               side.tex_name(r.main_pid) or "-"))
    log("  -> 'body' = the [body] meshes · 'all' = every mesh · or type "
        "comma-separated names from the list above")
    return [r.name for r in side.smrs]

def _select_meshes(arg, side):
    """'body' -> meshes sharing the body material's _MainTex; 'all' -> every
    skinned mesh; anything else -> comma-separated mesh names."""
    arg = (arg or "body").strip()
    if arg == "all":
        return list(side.smrs)
    if arg == "body":
        if side.body.main_pid:
            sel = [r for r in side.smrs if r.main_pid == side.body.main_pid]
        else:
            sel = []
        return sel or [side.body]
    names = {s.strip() for s in arg.split(",") if s.strip()}
    sel = [r for r in side.smrs if r.name in names]
    missing = names - {r.name for r in sel}
    if missing:
        raise ValueError("mesh name(s) not in %s: %s  (has: %s)"
                         % (os.path.basename(side.path), ", ".join(sorted(missing)),
                            ", ".join(r.name for r in side.smrs)))
    return sel

# --------------------------------------------------------------------------- #
#  Vertex-data edits done in the typetree (shared codec from sifas_fbx)        #
# --------------------------------------------------------------------------- #
def _remap_uv0(F, mesh, side_fn):
    """Apply side_fn to every U of TexCoord0 inside mesh['m_VertexData'] bytes."""
    vc, chans, stride, start, _ = F.stream_layout(mesh)
    if not chans[F.CH_UV0].get("dimension", 0):
        return False
    buf = bytearray(bytes(mesh["m_VertexData"]["m_DataSize"]))
    u8 = F.np.frombuffer(buf, F.np.uint8)
    uv = F.read_attr(u8, chans, F.CH_UV0, stride, start, vc)
    if uv is None:
        return False
    uv[:, 0] = side_fn(uv[:, 0])
    F.write_attr(u8, uv, chans, F.CH_UV0, stride, start, vc)
    mesh["m_VertexData"]["m_DataSize"] = bytes(buf)
    return True

def _missing_bone_report(F, rec, base_bone_names):
    """(sorted missing-bone names, verts fully on missing bones, verts partly)."""
    vc, chans, stride, start, _ = F.stream_layout(rec.mesh)
    if not chans[F.CH_BLENDWEIGHT].get("dimension", 0):
        return [], 0, 0
    u8 = F.np.frombuffer(bytearray(bytes(rec.mesh["m_VertexData"]["m_DataSize"])), F.np.uint8)
    bw = F.read_attr(u8, chans, F.CH_BLENDWEIGHT, stride, start, vc)
    bi = F.read_attr(u8, chans, F.CH_BLENDINDICES, stride, start, vc)
    miss_idx = {i for i, n in enumerate(rec.bones)
                if n is not None and n not in base_bone_names}
    if not miss_idx:
        return [], 0, 0
    on_missing = F.np.isin(bi, list(miss_idx)) & (bw > 0)
    wmiss = (bw * on_missing).sum(1)
    wtot = bw.sum(1)
    full = int(((wmiss >= wtot - 1e-6) & (wtot > 0)).sum())
    part = int(((wmiss > 0) & (wmiss < wtot - 1e-6)).sum())
    used = set(F.np.unique(bi[on_missing]).tolist())
    return sorted(rec.bones[i] for i in used), full, part

def _reskin_missing(F, rec, base_bone_names, donor_parent, log):
    """Re-target every influence on a bone the base lacks onto its nearest
    ancestor (following the donor hierarchy) that the base DOES have and that
    is in this renderer's bone list. Weights are merged per vertex."""
    vc, chans, stride, start, _ = F.stream_layout(rec.mesh)
    if not chans[F.CH_BLENDWEIGHT].get("dimension", 0):
        return 0
    idx_of = {n: i for i, n in enumerate(rec.bones) if n}
    repl = {}
    for i, n in enumerate(rec.bones):
        if n is None or n in base_bone_names:
            continue
        cur, hops = n, 0
        while hops < 64:
            cur = donor_parent.get(cur); hops += 1
            if cur is None:
                break
            if cur in base_bone_names and cur in idx_of:
                repl[i] = idx_of[cur]; break
        if i not in repl:
            repl[i] = idx_of.get("Hips", 0)
    if not repl:
        return 0
    buf = bytearray(bytes(rec.mesh["m_VertexData"]["m_DataSize"]))
    u8 = F.np.frombuffer(buf, F.np.uint8)
    bw = F.read_attr(u8, chans, F.CH_BLENDWEIGHT, stride, start, vc)
    bi = F.read_attr(u8, chans, F.CH_BLENDINDICES, stride, start, vc)
    hit_rows = F.np.nonzero((F.np.isin(bi, list(repl)) & (bw > 0)).any(1))[0]
    for v in hit_rows:
        acc = {}
        for k in range(bi.shape[1]):
            w = float(bw[v, k])
            if w <= 0:
                continue
            b = int(bi[v, k])
            b = repl.get(b, b)
            acc[b] = acc.get(b, 0.0) + w
        items = sorted(acc.items(), key=lambda kv: -kv[1])[:4]
        s = sum(w for _b, w in items) or 1.0
        for k in range(4):
            if k < len(items):
                bi[v, k] = items[k][0]; bw[v, k] = items[k][1] / s
            else:
                bi[v, k] = 0; bw[v, k] = 0.0
    F.write_attr(u8, bw, chans, F.CH_BLENDWEIGHT, stride, start, vc)
    F.write_attr(u8, bi.astype(F.np.float64), chans, F.CH_BLENDINDICES, stride, start, vc)
    rec.mesh["m_VertexData"]["m_DataSize"] = bytes(buf)
    named = sorted({rec.bones[i] for i in repl if rec.bones[i]})
    log("  re-skinned %d vert(s) of '%s' off %d missing bone(s): %s"
        % (len(hit_rows), rec.name, len(named), ", ".join(named)))
    return len(hit_rows)

def _bone_closure(names, parent):
    out = set(names)
    changed = True
    while changed:
        changed = False
        for n in list(out):
            p = parent.get(n)
            if p and p not in out:
                out.add(p); changed = True
    return out

# --------------------------------------------------------------------------- #
#  Core: combine two models into one FBX (+ atlases + prepared bundle)         #
# --------------------------------------------------------------------------- #
def combine_models(base_path, donor_path, out_fbx,
                   texdir=None, out_bundle=None, skip_bundle=False,
                   base_meshes="all", donor_meshes="body", suffix="_D",
                   gutter_px=4, merge_rim=True, mipmaps=True,
                   reskin_missing=False, dry_run=False, log=print):
    t0 = time.time()
    log("[info] loading engine (a first run may auto-install numpy/UnityPy)…")
    F = _load_engine()
    np = F.np
    from PIL import Image
    from UnityPy.enums import TextureFormat

    stem = os.path.splitext(out_fbx)[0]
    if texdir is None:
        texdir = stem + "_tex"
    if out_bundle is None and not skip_bundle:
        out_bundle = stem + "_atlas.unity"

    log("[info] reading base %s…" % os.path.basename(base_path))
    base = _Side(F, base_path, "base")
    log("[info] reading donor %s…" % os.path.basename(donor_path))
    donor = _Side(F, donor_path, "donor")

    base_sel = _select_meshes(base_meshes, base)
    donor_sel = _select_meshes(donor_meshes, donor)
    def _usable(sel, label):
        out = []
        for r in sel:
            ok, why = _mesh_ok(F, r.mesh)
            if ok:
                out.append(r)
            else:
                log("[warn] %s mesh '%s' skipped: %s" % (label, r.name, why))
        return out
    base_sel = _usable(base_sel, "base")
    donor_sel = _usable(donor_sel, "donor")
    if not base_sel or not donor_sel:
        raise ValueError("no usable mesh left on the %s side (see warnings above)"
                         % ("base" if not base_sel else "donor"))
    if not suffix:
        clash = {r.name for r in base_sel} & {r.name for r in donor_sel}
        if clash:
            raise ValueError("empty --suffix but both models have mesh(es) named: %s"
                             % ", ".join(sorted(clash)))

    log("[info] base  %s: %s" % (os.path.basename(base_path),
                                 ", ".join(r.name for r in base_sel)))
    log("[info] donor %s: %s" % (os.path.basename(donor_path),
                                 ", ".join(r.name + suffix for r in donor_sel)))

    # ---- atlas images ----------------------------------------------------- #
    if not base.body.main_pid:
        raise ValueError("base body material has no _MainTex — cannot build an atlas")
    if not donor.body.main_pid:
        raise ValueError("donor body material has no _MainTex — cannot build an atlas")
    log("[info] decoding textures / building atlases…")
    g, uL, uR = _uv_halves(gutter_px)
    atlas_main = _combine_images(base.tex_image(base.body.main_pid),
                                 donor.tex_image(donor.body.main_pid), g)
    main_name = base.tex_name(base.body.main_pid)
    log("[ok] _MainTex atlas %dx%d  (left=base '%s', right=donor '%s')"
        % (atlas_main.width, atlas_main.height, main_name,
           donor.tex_name(donor.body.main_pid)))
    atlas_rim = rim_name = None
    if merge_rim:
        if base.body.rim_pid:
            try:
                bimg = base.tex_image(base.body.rim_pid)
            except RuntimeError as ex:
                bimg = None
                log("[warn] %s" % ex)
                log("[warn] rim atlas skipped (the main atlas is unaffected)")
            if bimg is not None:
                dimg = None
                if donor.body.rim_pid:
                    try:
                        dimg = donor.tex_image(donor.body.rim_pid)
                    except RuntimeError as ex:
                        log("[warn] %s" % ex)
                if dimg is None:
                    dimg = Image.new("RGBA", bimg.size, (0, 0, 0, 255))
                    log("[warn] donor has no usable _RimlightTex — its atlas half is black (no rim)")
                atlas_rim = _combine_images(bimg, dimg, g)
                rim_name = base.tex_name(base.body.rim_pid)
                log("[ok] _RimlightTex atlas %dx%d" % (atlas_rim.width, atlas_rim.height))
        elif donor.body.rim_pid:
            log("[warn] base has no _RimlightTex slot to hold a rim atlas — rim skipped "
                "(the donor's rim map cannot be carried into the base bundle)")

    # ---- UV remap: every mesh on the body material moves into its half ----- #
    # Base meshes are remapped in the loaded env (also saved into the atlas
    # bundle, which therefore stays valid in-game on its own). Donor meshes are
    # remapped in memory only — the donor bundle is never written.
    def _is_atlased(rec, side):
        return bool(side.body.main_pid) and rec.main_pid == side.body.main_pid
    for side, fn in ((base, uL), (donor, uR)):
        for rec in side.smrs:
            if _is_atlased(rec, side) and _mesh_ok(F, rec.mesh)[0]:
                try:
                    remapped = _remap_uv0(F, rec.mesh, fn)
                except NotImplementedError as ex:
                    raise ValueError(
                        "mesh '%s': unsupported vertex data (%s) — this tool "
                        "needs plain uncompressed SIFAS meshes" % (rec.name, ex))
                if remapped:
                    if side is base:
                        rec.mesh_obj.save_typetree(rec.mesh)
                else:
                    log("[warn] %s '%s': no UV0 to remap" % (side.label, rec.name))

    # ---- donor bones the base bundle cannot express ------------------------ #
    base_body_bones = {n for n in base.body.bones if n}
    all_missing = {}
    for rec in donor_sel:
        names, full, part = _missing_bone_report(F, rec, base_body_bones)
        if names:
            all_missing[rec.name] = (names, full, part)
    if all_missing:
        log("[warn] donor bones MISSING from the base body renderer "
            "(their weights are dropped at re-import):")
        for mn, (names, full, part) in all_missing.items():
            log("  %s%s: %s  (%d vert(s) fully, %d partly on them)"
                % (mn, suffix, ", ".join(names), full, part))
        if reskin_missing:
            for rec in donor_sel:
                if rec.name in all_missing:
                    _reskin_missing(F, rec, base_body_bones, donor.parent, log)
        else:
            log("  -> keep them and re-weight in Blender, re-run with "
                "--reskin-missing, or add the bones to the base with "
                "costume_transplant.py first")

    # ---- combined skeleton -------------------------------------------------- #
    base_bones = _bone_closure({n for r in base.smrs for n in r.bones if n}, base.parent)
    donor_bones = _bone_closure({n for r in donor_sel for n in r.bones if n}, donor.parent)
    donor_only = donor_bones - base_bones
    local_u = dict(donor.local); local_u.update(base.local)
    world_u = dict(donor.world); world_u.update(base.world)
    parent_u = dict(donor.parent); parent_u.update(base.parent)
    all_bones = base_bones | donor_bones
    log("[ok] skeleton: %d bones (%d from base, %d donor-only%s)"
        % (len(all_bones), len(base_bones), len(donor_only),
           ": " + ", ".join(sorted(donor_only)) if donor_only else ""))
    shared = [n for n in donor_bones & base_bones
              if n in base.world and n in donor.world]
    if shared:
        dmax = max(float(np.linalg.norm(base.world[n][:3, 3] - donor.world[n][:3, 3]))
                   for n in shared)
        if dmax > 0.02:
            log("[warn] the two models' rest poses differ by up to %.0f mm — donor "
                "parts may sit slightly offset in Blender (fix by hand there)" % (dmax * 1000))

    if dry_run:
        log("  [dry run] would write %s + %s%s"
            % (out_fbx, texdir, (" + " + out_bundle) if out_bundle else ""))
        return None

    # ---- FBX assembly (same document layout as sifas_fbx.export) ----------- #
    log("[info] writing combined FBX…")
    FNode, C = F.FNode, "C"
    bone_model_id = {n: F._nid() for n in all_bones}
    MIRROR = F.MIRROR
    objects = FNode("Objects")
    conns = FNode("Connections")
    pose = FNode("Pose", [('L', F._nid()), ('S', F._name_class("BindPose", "Pose")),
                          ('S', "BindPose")]).add(
        FNode("Type", [('S', "BindPose")]), FNode("Version", [('I', 100)]),
        FNode("NbPoseNodes", [('I', len(bone_model_id))]))
    for n, mid in bone_model_id.items():
        Ln = local_u.get(n, np.eye(4))
        t = Ln[:3, 3].copy(); t[0] *= -1
        Rm = MIRROR[:3, :3] @ Ln[:3, :3] @ MIRROR[:3, :3]
        eul = F._mat_to_euler_xyz(Rm)
        objects.add(FNode("Model", [('L', mid), ('S', F._name_class(n, "Model")),
                                    ('S', "LimbNode")]).add(
            FNode("Version", [('I', 232)]),
            FNode("Properties70").add(
                FNode("P", [('S', "Lcl Translation"), ('S', "Lcl Translation"), ('S', ""), ('S', "A"),
                            ('D', float(t[0])), ('D', float(t[1])), ('D', float(t[2]))]),
                FNode("P", [('S', "Lcl Rotation"), ('S', "Lcl Rotation"), ('S', ""), ('S', "A"),
                            ('D', float(eul[0])), ('D', float(eul[1])), ('D', float(eul[2]))]))))
        p = parent_u.get(n)
        conns.add(FNode(C, [('S', "OO"), ('L', mid), ('L', bone_model_id.get(p, 0))]))
        TL = MIRROR @ world_u.get(n, np.eye(4)) @ MIRROR
        pose.add(FNode("PoseNode").add(FNode("Node", [('L', mid)]),
                                       FNode("Matrix", [('d', TL.T.reshape(-1))])))

    os.makedirs(texdir, exist_ok=True)
    atlas_main.save(os.path.join(texdir, main_name + ".png"))
    if atlas_rim is not None:
        atlas_rim.save(os.path.join(texdir, rim_name + ".png"))

    n_models = len(bone_model_id)
    n_def = 0
    n_meshes = 0
    tex_done = {}
    total_v = total_t = 0
    for side, sel, sfx in ((base, base_sel, ""), (donor, donor_sel, suffix)):
        for rec in sel:
            name_out = rec.name + sfx
            if rec.mesh.get("m_Shapes", {}).get("shapes"):
                log("[warn] %s: blend shapes not round-tripped" % name_out)
            geo_id = F._nid()
            try:
                geo, skin, clusters, cl_ids, has_skin = F._geo_and_skin(
                    rec.mesh, rec.smr_tt, rec.bones, world_u, bone_model_id,
                    geo_id, name_out)
            except NotImplementedError as ex:
                raise ValueError(
                    "mesh '%s': unsupported vertex data (%s) — this tool needs "
                    "plain uncompressed SIFAS meshes" % (name_out, ex))
            mesh_model_id = F._nid()
            objects.add(FNode("Model", [('L', mesh_model_id),
                                        ('S', F._name_class(name_out, "Model")),
                                        ('S', "Mesh")]).add(
                FNode("Version", [('I', 232)]),
                FNode("Properties70").add(
                    FNode("P", [('S', "Lcl Scaling"), ('S', "Lcl Scaling"), ('S', ""), ('S', "A"),
                                ('D', 1.0), ('D', 1.0), ('D', 1.0)]))))
            objects.add(geo)
            conns.add(FNode(C, [('S', "OO"), ('L', mesh_model_id), ('L', 0)]))
            conns.add(FNode(C, [('S', "OO"), ('L', geo_id), ('L', mesh_model_id)]))
            n_models += 1; n_meshes += 1
            if has_skin and skin is not None:
                objects.add(skin)
                conns.add(FNode(C, [('S', "OO"), ('L', skin.props[0][1]), ('L', geo_id)]))
                for c in clusters:
                    objects.add(c)
                for bn, cid in cl_ids.items():
                    conns.add(FNode(C, [('S', "OO"), ('L', cid), ('L', skin.props[0][1])]))
                    conns.add(FNode(C, [('S', "OO"), ('L', bone_model_id[bn]), ('L', cid)]))
                n_def += 1 + len(clusters)
            # material: atlased meshes share the atlas texture; others keep
            # their own texture (written to texdir so Blender can show it)
            if _is_atlased(rec, side):
                tex_name = main_name
            else:
                tex_name = side.tex_name(rec.main_pid)
                if tex_name:
                    png = os.path.join(texdir, tex_name + ".png")
                    if not os.path.exists(png):
                        try:
                            side.tex_image(rec.main_pid).save(png)
                        except Exception as ex:
                            log("[warn] texture '%s': decode failed (%s) — FBX will "
                                "reference a missing file" % (tex_name, ex))
            mat_name = (rec.mat_name or "mat") + sfx
            mat, tex, vid, (mat_id, tex_id, vid_id) = F._material_nodes(
                mat_name, tex_name, texdir)
            objects.add(mat)
            conns.add(FNode(C, [('S', "OO"), ('L', mat_id), ('L', mesh_model_id)]))
            if tex is not None and tex_name not in tex_done:
                objects.add(vid); objects.add(tex)
                conns.add(FNode(C, [('S', "OP"), ('L', tex_id), ('L', mat_id), ('S', "DiffuseColor")]))
                conns.add(FNode(C, [('S', "OO"), ('L', vid_id), ('L', tex_id)]))
                tex_done[tex_name] = tex_id
            elif tex is not None:
                conns.add(FNode(C, [('S', "OP"), ('L', tex_done[tex_name]), ('L', mat_id), ('S', "DiffuseColor")]))
            vc = rec.mesh["m_VertexData"]["m_VertexCount"]
            nt = F.read_indices(rec.mesh).size // 3
            total_v += vc; total_t += nt
            log("[ok] mesh '%s': %d verts, %d tris, %s%s"
                % (name_out, vc, nt, "skinned" if has_skin else "static",
                   ", atlas UVs" if _is_atlased(rec, side) else ""))

    objects.add(pose)
    header = FNode("FBXHeaderExtension").add(
        FNode("FBXHeaderVersion", [('I', 1003)]), FNode("FBXVersion", [('I', 7500)]),
        FNode("Creator", [('S', "sifas_fbx_combine.py")]))
    gs = FNode("GlobalSettings").add(FNode("Version", [('I', 1000)]), FNode("Properties70").add(
        FNode("P", [('S', "UpAxis"), ('S', "int"), ('S', "Integer"), ('S', ""), ('I', 1)]),
        FNode("P", [('S', "UpAxisSign"), ('S', "int"), ('S', "Integer"), ('S', ""), ('I', 1)]),
        FNode("P", [('S', "FrontAxis"), ('S', "int"), ('S', "Integer"), ('S', ""), ('I', 2)]),
        FNode("P", [('S', "FrontAxisSign"), ('S', "int"), ('S', "Integer"), ('S', ""), ('I', 1)]),
        FNode("P", [('S', "CoordAxis"), ('S', "int"), ('S', "Integer"), ('S', ""), ('I', 0)]),
        FNode("P", [('S', "CoordAxisSign"), ('S', "int"), ('S', "Integer"), ('S', ""), ('I', 1)]),
        FNode("P", [('S', "UnitScaleFactor"), ('S', "double"), ('S', "Number"), ('S', ""), ('D', 1.0)])))
    documents = FNode("Documents").add(
        FNode("Count", [('I', 1)]),
        FNode("Document", [('L', F._nid()), ('S', "Scene"), ('S', "Scene")]).add(
            FNode("RootNode", [('I', 0)])))
    definitions = FNode("Definitions").add(
        FNode("Version", [('I', 100)]),
        FNode("Count", [('I', n_models + n_def + len(tex_done) * 2 + 5)]),
        FNode("ObjectType", [('S', "Model")]).add(FNode("Count", [('I', n_models)])),
        FNode("ObjectType", [('S', "Geometry")]).add(FNode("Count", [('I', n_meshes)])),
        FNode("ObjectType", [('S', "Material")]).add(FNode("Count", [('I', n_meshes)])),
        FNode("ObjectType", [('S', "Texture")]).add(FNode("Count", [('I', len(tex_done))])),
        FNode("ObjectType", [('S', "Video")]).add(FNode("Count", [('I', len(tex_done))])),
        FNode("ObjectType", [('S', "Deformer")]).add(FNode("Count", [('I', n_def)])),
        FNode("ObjectType", [('S', "Pose")]).add(FNode("Count", [('I', 1)])))
    takes = FNode("Takes").add(FNode("Current", [('S', "")]))

    os.makedirs(os.path.dirname(os.path.abspath(out_fbx)), exist_ok=True)
    with open(out_fbx, "wb") as f:
        f.write(F.fbx_serialize([header, gs, documents, definitions, objects, conns, takes]))
    log("[ok] combined FBX: %d mesh(es), %d verts, %d tris, %d bones -> %s"
        % (n_meshes, total_v, total_t, len(bone_model_id), out_fbx))
    log(_tr("Saved: %s") % out_fbx)

    # ---- prepared re-import bundle (base + atlas textures + left-half UVs) - #
    if out_bundle:
        log("[info] writing atlas bundle…")
        for pid, img in ((base.body.main_pid, atlas_main), (base.body.rim_pid, atlas_rim)):
            if not pid or img is None:
                continue
            tex = base.uid[pid].read()
            mc = int(math.floor(math.log2(max(img.size)))) + 1 if mipmaps else 1
            tex.set_image(img, target_format=TextureFormat.RGBA32, mipmap_count=mc)
            tex.save()
        os.makedirs(os.path.dirname(os.path.abspath(out_bundle)) or ".", exist_ok=True)
        with open(out_bundle, "wb") as f:
            f.write(base.env.file.save(packer="original"))
        log("[ok] atlas bundle (re-import target): %s" % out_bundle)

    _write_howto(stem, out_fbx, texdir, out_bundle, main_name, rim_name,
                 suffix, all_missing, log)
    log("[done] in %.1fs" % (time.time() - t0))
    return out_fbx

def _write_howto(stem, out_fbx, texdir, out_bundle, main_name, rim_name,
                 suffix, all_missing, log):
    lines = [
        "SIFAS FBX Combine — finishing this mod in Blender",
        "==================================================",
        "combined FBX : %s" % out_fbx,
        "textures     : %s  (atlas: %s.png%s)"
        % (texdir, main_name, (", %s.png" % rim_name) if rim_name else ""),
        "atlas bundle : %s" % (out_bundle or "(skipped)"),
        "",
        "1) Blender > File > Import > FBX. Both models share one armature;",
        "   donor meshes end with '%s'." % suffix,
        "2) Delete the parts you don't want, edit freely. Keep the armature",
        "   modifier and the vertex groups on everything you keep.",
        "3) Donor pieces you keep must end up in an object NAMED like a base",
        "   mesh: select the donor piece, shift-select e.g. 'Body', Ctrl+J",
        "   (or rename it). Objects whose name matches no base mesh are",
        "   ignored at re-import.",
        "4) File > Export > FBX (BINARY, with the armature; default settings",
        "   are fine — do not retick 'ASCII').",
        "5) Re-import into the ATLAS bundle (not the original base bundle):",
        "   python3 sifas_fbx.py import --fbx edited.fbx --bundle %s --out final.unity"
        % (out_bundle or "<atlas bundle>"),
        "",
        "UV note: base UVs live in the LEFT atlas half, donor UVs in the",
        "RIGHT half. Don't re-unwrap; keep islands inside their half.",
    ]
    if all_missing:
        lines.append("")
        lines.append("Bones the base bundle does NOT have (weights on them are")
        lines.append("dropped at re-import — re-weight these in Blender, or re-run")
        lines.append("with --reskin-missing):")
        for mn, (names, full, part) in all_missing.items():
            lines.append("  %s%s: %s" % (mn, suffix, ", ".join(names)))
    txt = stem + "_howto.txt"
    try:
        with open(txt, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        log("[ok] next steps written to %s" % txt)
    except OSError as ex:
        log("[warn] could not write %s (%s)" % (txt, ex))
    log("")
    for ln in lines[6:]:
        log(ln)

# --------------------------------------------------------------------------- #
#  CLI                                                                         #
# --------------------------------------------------------------------------- #
def main_cli(argv):
    p = argparse.ArgumentParser(
        description="Combine two SIFAS models into one Blender-ready FBX with "
                    "an automatic _MainTex + _RimlightTex atlas.",
        epilog="after Blender:  python3 sifas_fbx.py import --fbx edited.fbx "
               "--bundle <out>_atlas.unity --out final.unity")
    p.add_argument("--scan", metavar="BUNDLE",
                   help="just list a bundle's meshes (names / verts / bones / "
                        "textures) and exit — use it to fill --base-meshes / "
                        "--donor-meshes")
    p.add_argument("--base",
                   help="base model bundle (keeps its skeleton; re-import target)")
    p.add_argument("--donor",
                   help="donor model bundle (its meshes are added with a suffix)")
    p.add_argument("--out", help="output FBX (default: <base>_combined.fbx)")
    p.add_argument("--texdir", default=None,
                   help="texture folder for the FBX (default: <out>_tex)")
    p.add_argument("--out-bundle", default=None,
                   help="atlas bundle to re-import into (default: <out>_atlas.unity)")
    p.add_argument("--skip-bundle", action="store_true",
                   help="do not write the atlas bundle")
    p.add_argument("--base-meshes", default="all", metavar="all|body|A,B",
                   help="base meshes to put in the FBX (default all)")
    p.add_argument("--donor-meshes", default="body", metavar="body|all|A,B",
                   help="donor meshes to bring over (default body: every mesh "
                        "on the donor's body material)")
    p.add_argument("--suffix", default="_D",
                   help="suffix on donor mesh/material names in the FBX (default _D)")
    p.add_argument("--gutter", type=int, default=4, help="atlas gutter in px")
    p.add_argument("--no-rim", action="store_true", help="do not merge the rim map")
    p.add_argument("--no-mipmaps", action="store_true",
                   help="no mipmaps in the atlas bundle textures")
    p.add_argument("--reskin-missing", action="store_true",
                   help="re-target donor weights on bones the base lacks onto the "
                        "nearest ancestor bone the base has")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args(argv)
    if a.scan:
        scan_model(a.scan)
        return
    if not a.base or not a.donor:
        p.error("--base and --donor are required (or use --scan BUNDLE)")
    out = a.out or (os.path.splitext(a.base)[0] + "_combined.fbx")
    combine_models(a.base, a.donor, out, texdir=a.texdir,
                   out_bundle=a.out_bundle, skip_bundle=a.skip_bundle,
                   base_meshes=a.base_meshes, donor_meshes=a.donor_meshes,
                   suffix=a.suffix, gutter_px=a.gutter, merge_rim=not a.no_rim,
                   mipmaps=not a.no_mipmaps, reskin_missing=a.reskin_missing,
                   dry_run=a.dry_run)

# --------------------------------------------------------------------------- #
#  Text menu (no display / Termux)                                            #
# --------------------------------------------------------------------------- #
def main_menu():
    print("=== %s ===" % _tr("SIFAS FBX Combine"))
    base = input(_tr("Base model (re-import target):") + " ").strip()
    donor = input(_tr("Donor model (parts to bring):") + " ").strip()
    dflt = os.path.splitext(base)[0] + "_combined.fbx"
    out = input(_tr("Output FBX:") + " [%s] " % dflt).strip() or dflt
    print(_tr("Donor meshes:"))
    opts = [("body", "body material only"), ("all", "all meshes"), ("custom", "custom names…")]
    for i, (_k, lbl) in enumerate(opts):
        print("  %d) %s" % (i + 1, _tr(lbl)))
    sel = input("> ").strip() or "1"
    try:
        key = opts[int(sel) - 1][0]
    except Exception:
        key = "body"
    if key == "custom":
        try:
            scan_model(donor)
        except Exception as e:
            print(_tr("ERROR: %s") % e)
        key = input(_tr("Custom names (comma):") + " ").strip() or "body"
    combine_models(base, donor, out, donor_meshes=key)

# --------------------------------------------------------------------------- #
#  GUI (tkinter)                                                               #
# --------------------------------------------------------------------------- #
def main_gui():
    import threading, queue
    import tkinter as tk
    from tkinter import ttk, filedialog
    root = tk.Tk()
    root.title(_tr("SIFAS FBX Combine"))
    q = queue.Queue()

    def row(r, label):
        ttk.Label(root, text=_tr(label)).grid(row=r, column=0, sticky="w", padx=6, pady=3)
        e = ttk.Entry(root, width=52); e.grid(row=r, column=1, padx=4, pady=3)
        return e

    base_e = row(0, "Base model (re-import target):")
    donor_e = row(1, "Donor model (parts to bring):")
    out_e = row(2, "Output FBX:")
    tex_e = row(3, "Texture folder (blank=auto):")
    bnd_e = row(4, "Atlas bundle out (blank=auto):")

    def browse(entry, save=False, fbx=False):
        if save:
            path = filedialog.asksaveasfilename(
                defaultextension=".fbx" if fbx else ".unity",
                filetypes=[("FBX", "*.fbx")] if fbx else [("Unity bundle", "*.unity *.unity3d"),
                                                          ("All files", "*.*")])
        else:
            path = filedialog.askopenfilename()
        if path:
            entry.delete(0, "end"); entry.insert(0, path)
    ttk.Button(root, text=_tr("Browse…"), command=lambda: browse(base_e)).grid(row=0, column=2, padx=4)
    ttk.Button(root, text=_tr("Browse…"), command=lambda: browse(donor_e)).grid(row=1, column=2, padx=4)
    ttk.Button(root, text=_tr("Browse…"), command=lambda: browse(out_e, True, True)).grid(row=2, column=2, padx=4)
    ttk.Button(root, text=_tr("Browse…"), command=lambda: browse(bnd_e, True)).grid(row=4, column=2, padx=4)

    MESH_OPTS = [("body", "body material only"), ("all", "all meshes"), ("custom", "custom names…")]
    selrow = ttk.Frame(root); selrow.grid(row=5, column=1, columnspan=2, sticky="w")
    ttk.Label(selrow, text=_tr("Donor meshes:")).pack(side="left")
    donor_box = ttk.Combobox(selrow, state="readonly", width=18,
                             values=[_tr(lbl) for _k, lbl in MESH_OPTS])
    donor_box.current(0); donor_box.pack(side="left", padx=4)
    donor_custom = ttk.Entry(selrow, width=22); donor_custom.pack(side="left", padx=2)
    ttk.Label(selrow, text=_tr("Donor name suffix:")).pack(side="left", padx=(10, 0))
    suffix_e = ttk.Entry(selrow, width=5); suffix_e.insert(0, "_D"); suffix_e.pack(side="left")

    def scan_click():
        base, donor = base_e.get().strip(), donor_e.get().strip()
        if not base and not donor:
            q.put(_tr("Pick a base and a donor first.")); return
        def sw():
            try:
                for pth in (base, donor):
                    if pth:
                        scan_model(pth, log=put)
            except BaseException as e:
                put(_tr("ERROR: %s") % e)
        threading.Thread(target=sw, daemon=True).start()
    ttk.Button(selrow, text=_tr("Scan meshes"), command=scan_click).pack(side="left", padx=(10, 0))

    rim_var = tk.BooleanVar(value=True)
    mip_var = tk.BooleanVar(value=True)
    reskin_var = tk.BooleanVar(value=False)
    skipb_var = tk.BooleanVar(value=False)
    dry_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(root, text=_tr("Merge rim map too"), variable=rim_var).grid(row=6, column=1, sticky="w")
    ttk.Checkbutton(root, text=_tr("Generate mipmaps"), variable=mip_var).grid(row=7, column=1, sticky="w")
    ttk.Checkbutton(root, text=_tr("Re-skin weights on bones missing from base"),
                    variable=reskin_var).grid(row=8, column=1, sticky="w")
    ttk.Checkbutton(root, text=_tr("Skip atlas bundle"), variable=skipb_var).grid(row=9, column=1, sticky="w")
    ttk.Checkbutton(root, text=_tr("Dry run (no write)"), variable=dry_var).grid(row=10, column=1, sticky="w")

    log = tk.Text(root, height=14, width=76); log.grid(row=12, column=0, columnspan=3, padx=6, pady=6)
    def put(msg): q.put(str(msg))

    def work():
        try:
            base = base_e.get().strip(); donor = donor_e.get().strip()
            if not base or not donor:
                put(_tr("Pick a base and a donor first.")); return
            out = out_e.get().strip() or (os.path.splitext(base)[0] + "_combined.fbx")
            key = MESH_OPTS[donor_box.current()][0]
            if key == "custom":
                key = donor_custom.get().strip() or "body"
            put(_tr("Working…"))
            combine_models(base, donor, out,
                           texdir=tex_e.get().strip() or None,
                           out_bundle=bnd_e.get().strip() or None,
                           skip_bundle=skipb_var.get(),
                           donor_meshes=key,
                           suffix=suffix_e.get().strip() or "_D",
                           merge_rim=rim_var.get(), mipmaps=mip_var.get(),
                           reskin_missing=reskin_var.get(),
                           dry_run=dry_var.get(), log=put)
            put(_tr("Done."))
        except BaseException as e:           # incl. SystemExit from _load_engine —
            put(_tr("ERROR: %s") % e)        # a silent thread death looked like an
            put(traceback.format_exc())      # endless "Working…"

    def run():
        threading.Thread(target=work, daemon=True).start()
    ttk.Button(root, text=_tr("Run"), command=run).grid(row=11, column=1, pady=4)

    ttk.Label(root, text=_tr("Language:")).grid(row=13, column=0, sticky="w", padx=6)
    lang_var = tk.StringVar(value=dict(_LANG_NAMES)[_LANG.lang])
    def on_lang(_e=None):
        for code, name in _LANG_NAMES:
            if name == lang_var.get():
                _LANG.set(code)
        root.destroy(); main_gui()
    lb = ttk.Combobox(root, textvariable=lang_var, state="readonly",
                      values=[n for _c, n in _LANG_NAMES]); lb.grid(row=13, column=1, sticky="w")
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
