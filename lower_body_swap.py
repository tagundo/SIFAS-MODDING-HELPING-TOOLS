#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
lower_body_swap.py — SIFAS lower-body skin graft (with texture atlas merge)

Fixes the "detached thighs / 11-shape" problem: some SIFAS costumes ship a body
mesh whose hip / lower-belly / buttock / upper-thigh skin was deleted (it is
normally hidden under the outfit), so when those parts show they look like two
separate leg tubes that do not connect.

This tool grafts the LOWER-BODY SKIN (Hips + legs, down to a configurable cut
height) from a *donor* model that still has a complete lower body, onto a
*target* model — keeping the target's face, upper body and costume.

Because every SIFAS model of the same character shares one skeleton and rest
pose, donor skin is re-skinned to the target by matching bone NAMES, so it
deforms correctly in-game. Skin colour and the rim map are preserved by merging
the donor's body atlas with the target's into a single side-by-side atlas and
re-mapping UVs — the donor skin keeps sampling the donor texture.

Runs as a window (tkinter), a text menu, or a command line. English / 한국어 /
日本語 (see SIFAS_LANG). Verified on Unity 2018.4 uncompressed SIFAS bundles.

  pip install UnityPy Pillow numpy

CLI examples:
  # single, replace from the knee up (keep the target's socks/shoes)
  python lower_body_swap.py --target rv92it_0.unity --donor 1xnzdv_0.unity \
                            --out fixed.unity --cut above_thigh
  # batch: one donor onto every bundle in a folder (-> ~/sukusta/modded)
  python lower_body_swap.py --donor 1xnzdv_0.unity --batch ~/sukusta/extracted \
                            --cut whole
"""
import os, sys, json, math, struct, argparse, traceback

# --------------------------------------------------------------------------- #
#  Lazy / optional dependencies                                               #
# --------------------------------------------------------------------------- #
def _require(mod, pipname=None):
    try:
        return __import__(mod)
    except ImportError:
        raise SystemExit("This tool needs '%s'.  Install with:  pip install %s"
                         % (mod, pipname or mod))

def _require_unitypy():
    up = _require("UnityPy")
    return up

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
  "SIFAS Lower-Body Swap": "SIFAS 하반신 교체",
  "Donor (good lower body):": "도너 (정상 하반신):",
  "Target (broken / to fix):": "타겟 (교체할 모델):",
  "Output file / folder:": "출력 파일/폴더:",
  "Browse…": "찾아보기…",
  "Replace range (cut):": "교체 범위 (컷):",
  "Custom band  low Y:": "직접 범위  하한 Y:",
  "high Y:": "상한 Y:",
  "region:": "영역:",
  "Y guide: ankle .11 · calf .30 · knee .50 · thigh .67 · crotch .85 · belly .92 · waist 1.05":
    "높이 가이드: 발목 0.11 · 종아리 0.30 · 무릎 0.50 · 허벅지 0.67 · 사타구니 0.85 · 아랫배 0.92 · 허리 1.05",
  "Open skirt cap lift (0=off):": "치마 바닥캡 열기 (0=끔):",
  "edge:": "외각:",
  "Keep donor accessories (dagger/garter)": "도너 액세서리 유지 (단검/가터)",
  "Batch (target is a folder)": "일괄 처리 (타겟이 폴더)",
  "Merge rim map too": "Rim맵도 병합",
  "Generate mipmaps": "밉맵 생성",
  "Dry run (no write)": "미리보기만 (저장 안 함)",
  "Run": "실행",
  "Language:": "언어:",
  "fix detached thighs (hip/crotch only)": "11자 수정 (엉덩이/사타구니만)",
  "thigh & up (keep calf/shoes)": "허벅지 위로 (종아리/신발 유지)",
  "calf part & up": "종아리 일부 위로",
  "from calf & up (keep feet)": "종아리부터 위로 (발 유지)",
  "whole lower body": "하반신 전체",
  "custom height…": "직접 높이 입력…",
  "Done.": "완료.",
  "Working…": "작업 중…",
  "Pick a donor and a target first.": "먼저 도너와 타겟을 선택하세요.",
  "Saved: %s": "저장됨: %s",
  "ERROR: %s": "오류: %s",
  "no body mesh found in %s": "%s 에서 바디 메시를 찾지 못했습니다",
 },
 "ja": {
  "SIFAS Lower-Body Swap": "SIFAS 下半身入れ替え",
  "Donor (good lower body):": "ドナー (正常な下半身):",
  "Target (broken / to fix):": "ターゲット (修正する側):",
  "Output file / folder:": "出力ファイル/フォルダ:",
  "Browse…": "参照…",
  "Replace range (cut):": "置換範囲 (カット):",
  "Custom band  low Y:": "範囲指定  下限 Y:",
  "high Y:": "上限 Y:",
  "region:": "領域:",
  "Y guide: ankle .11 · calf .30 · knee .50 · thigh .67 · crotch .85 · belly .92 · waist 1.05":
    "高さ目安: 足首0.11 · ふくらはぎ0.30 · ひざ0.50 · 太もも0.67 · 股0.85 · 下腹0.92 · 腰1.05",
  "Open skirt cap lift (0=off):": "スカート底キャップを開く (0=無効):",
  "edge:": "外縁:",
  "Keep donor accessories (dagger/garter)": "ドナー装飾品を残す (短剣/ガーター)",
  "Batch (target is a folder)": "一括処理 (ターゲットがフォルダ)",
  "Merge rim map too": "リムマップも統合",
  "Generate mipmaps": "ミップマップ生成",
  "Dry run (no write)": "ドライラン (保存しない)",
  "Run": "実行",
  "Language:": "言語:",
  "fix detached thighs (hip/crotch only)": "離れた太ももを修正 (腰/股のみ)",
  "thigh & up (keep calf/shoes)": "太もも以上 (ふくらはぎ/靴を維持)",
  "calf part & up": "ふくらはぎ一部以上",
  "from calf & up (keep feet)": "ふくらはぎから上 (足を維持)",
  "whole lower body": "下半身全体",
  "custom height…": "高さを直接入力…",
  "Done.": "完了。",
  "Working…": "処理中…",
  "Pick a donor and a target first.": "先にドナーとターゲットを選択してください。",
  "Saved: %s": "保存しました: %s",
  "ERROR: %s": "エラー: %s",
  "no body mesh found in %s": "%s にボディメッシュが見つかりません",
 },
}

def _tr(text):
    return _TR.get(_LANG.lang, {}).get(text, text)

# --------------------------------------------------------------------------- #
#  SUKUSTA extracted -> modded convention                                     #
# --------------------------------------------------------------------------- #
def sukusta_dir():
    d = os.environ.get("SUKUSTA_DIR")
    if d:
        return d
    termux = os.path.expanduser("~/storage/downloads/sukusta")
    if os.path.isdir(termux):
        return termux
    return os.path.expanduser("~/sukusta")

def default_modded_path(target_path):
    base = sukusta_dir()
    ext = os.path.join(base, "extracted")
    mod = os.path.join(base, "modded")
    ap = os.path.abspath(target_path)
    if os.path.commonpath([ap, os.path.abspath(ext)]) == os.path.abspath(ext):
        rel = os.path.relpath(ap, os.path.abspath(ext))
        return os.path.join(mod, rel)
    return os.path.join(os.path.dirname(ap), "modded_" + os.path.basename(ap))

# --------------------------------------------------------------------------- #
#  Anatomy / region bone sets                                                 #
# --------------------------------------------------------------------------- #
ANATOMY = {
 "Hips","Spine","Spine1","Spine2","Neck","Head","Head_All","Head_End","Head_Face",
 "Head_Face_End","Head_Hair","Head_Hair_End","Neck_Hair","Reference","Move",
 "Hips_Position","HipsSize","BreastSize","LeftShoulder","RightShoulder","LeftArm",
 "RightArm","LeftArmRoll","RightArmRoll","LeftForeArm","RightForeArm",
 "LeftForeArmRoll","RightForeArmRoll","LeftHand","RightHand","LeftUpLeg","RightUpLeg",
 "LeftLeg","RightLeg","LeftFoot","RightFoot","LeftToeBase","RightToeBase",
 "LeftToeBase_End","RightToeBase_End","ShadowToeL","ShadowToeR",
}
for _s in ("Left","Right"):
    for _f in ("Thumb","Index","Middle","Ring","Pinky"):
        for _k in (1,2,3,4):
            ANATOMY.add("%sHand%s%d" % (_s,_f,_k))

LOWER = {"Hips","HipsSize","LeftUpLeg","RightUpLeg","LeftLeg","RightLeg",
         "LeftFoot","RightFoot","LeftToeBase","RightToeBase"}
# NOTE: HipsSize carries the buttocks / hip-sides / crotch skin — it MUST be in
# the lower-body region or those parts are left out of the graft.
# Actual LEG bones (no Hips/HipsSize).  Only mesh islands that contain a leg bone
# are treated as droppable leg/body geometry on the target; a waist accessory
# (e.g. a "Love Live!" rosette weighted only to Hips) has no leg bone, so it is
# never mistaken for body skin and deleted.
LEG_BONES = {"LeftUpLeg","RightUpLeg","LeftLeg","RightLeg",
             "LeftFoot","RightFoot","LeftToeBase","RightToeBase"}
# central body column (no arms / head / hands) — for bands that reach the belly
CENTRAL = LOWER | {"Spine","Spine1","Spine2"}

# Which bones may be replaced.  "lower" keeps the target's torso (crisp,
# anatomical waist boundary); the others let a vertical band reach up into the
# lower belly / abdomen.
REGIONS = {
 "lower":       LOWER,
 "lower_belly": LOWER | {"Spine"},
 "central":     CENTRAL,
}

INF = 1.0e9
WAIST = 0.92            # world Y near the top of the hips; default band top
# ---------------------------------------------------------------------------
# BODY-HEIGHT REFERENCE  (rest-pose world-space Y; measured on the SIFAS rig,
# identical across characters).  cut_low / cut_high are given in THESE units.
# Picture the model standing on the floor (Y=0), ~1.42 tall:
#
#   Y                     몸의 위치 (body landmark)
#   ----  --------------------------------------------------------------
#   1.42  머리 끝            top of head
#   1.40  머리               head
#   1.35  목                 neck
#   1.25  가슴               chest        (Spine2)
#   1.05  허리               waist        (Spine 1.00~1.07)
#   0.92  아랫배 / 골반 위    lower belly / top of pelvis   <- WAIST const
#   0.85  사타구니·엉덩이     crotch / buttocks   (HipsSize/Hips)
#   0.80  엉덩이 아래선       gluteal fold  <- the flat "fake skirt" cap sits here
#   0.67  허벅지 중간         mid-thigh    (UpLeg)
#   0.50  무릎               KNEE  <- clean vertex-coincident ring (best seam)
#   0.40  무릎 바로 아래      just below knee
#   0.30  종아리 중간         mid-calf     (Leg)
#   0.13  발목 위            above ankle
#   0.11  발목               ankle
#   0.00  발바닥 / 바닥       sole / floor
#
# A replaced band is [cut_low, cut_high].  cut_low = bottom of the swap,
# cut_high = top.  Example: cut_low 0.50, cut_high 0.96  ->  swap from the
# knee up to just below the waist (the classic "11-shape thigh" fix).
# SIFAS legs are vertex-coincident from ~0.40 to ~0.80, so a cut placed there
# joins seamlessly; the graft auto-snaps cut_low to the best ring near it.
# A "cut" preset is just a named (cut_low, cut_high) pair.  hip_fix only
# replaces the hip/crotch bridge (missing in "11-shape" bodies), keeping legs.
# ---------------------------------------------------------------------------
# (cut_low, cut_high) in the rest-pose Y units of the chart above.
CUT_PRESETS = {
 "hip_fix":     (0.500, 0.96),   # knee(0.50) -> just below waist(0.96).
                                 #  RECOMMENDED: join at the knee (a clean
                                 #  vertex-coincident ring), graft thigh+hip+
                                 #  buttocks up to the waist.  The graft also
                                 #  removes the flat "fake skirt bottom" cap.
 "above_thigh": (0.504, INF),    # knee up, no top limit (like hip_fix, may add belly)
 "calf_part":   (0.300, INF),    # mid-calf(0.30) up
 "from_calf":   (0.110, INF),    # ankle(0.11) up, keep the feet
 "whole":       (-INF,  INF),    # floor(0.0) up: the entire lower body
}
CUT_LABELS = [
 ("hip_fix",     "fix detached thighs (hip/crotch only)"),
 ("above_thigh", "thigh & up (keep calf/shoes)"),
 ("calf_part",   "calf part & up"),
 ("from_calf",   "from calf & up (keep feet)"),
 ("whole",       "whole lower body"),
 ("custom",      "custom range…"),
]

# --------------------------------------------------------------------------- #
#  Vertex / index codec  (uncompressed SIFAS m_VertexData)                     #
# --------------------------------------------------------------------------- #
_FMT_BYTES = {0:4, 1:2, 2:1, 3:1, 4:2, 5:2, 6:1, 7:1, 8:2, 9:2, 10:4, 11:4}

def _layout(tt):
    vd = tt["m_VertexData"]; n = vd["m_VertexCount"]; ch = vd["m_Channels"]
    strides = {}
    for c in ch:
        if c["dimension"] > 0:
            fb = _FMT_BYTES.get(c["format"], 4); s = c["stream"]
            strides[s] = max(strides.get(s, 0), c["offset"] + c["dimension"]*fb)
    order = sorted(strides); off = {}; cur = 0
    for s in order:
        off[s] = cur
        blk = strides[s]*n
        blk = (blk + 15)//16*16
        cur += blk
    return n, strides, off, order

def _uv_channel(tt):
    """Return (stream, byte_offset) of TexCoord0 (channel 4)."""
    c = tt["m_VertexData"]["m_Channels"][4]
    return c["stream"], c["offset"]

def _chan_locs(tt):
    """channel index -> (stream, offset, format, dim, byte_size) for active channels."""
    locs = {}
    for ci, c in enumerate(tt["m_VertexData"]["m_Channels"]):
        if c["dimension"] > 0:
            sz = c["dimension"] * _FMT_BYTES.get(c["format"], 4)
            locs[ci] = (c["stream"], c["offset"], c["format"], c["dimension"], sz)
    return locs

class BodyMesh:
    """Decoded body skinned mesh + its renderer / material / textures."""
    def __init__(self, env, path):
        self.env = env; self.path = path
        objs = list(env.objects); self.by_pid = {o.path_id: o for o in objs}
        self.mesh_obj = None; self.tt = None
        # body mesh = the one named "Body"; fall back to largest skinned mesh
        best = None
        for o in objs:
            if o.type.name == "Mesh":
                t = o.read_typetree()
                if t.get("m_Name") == "Body":
                    self.mesh_obj = o; self.tt = t
                vc = t.get("m_VertexData", {}).get("m_VertexCount", 0)
                if best is None or vc > best[0]:
                    best = (vc, o, t)
        if self.tt is None and best:
            _, self.mesh_obj, self.tt = best
        if self.tt is None:
            raise ValueError(_tr("no body mesh found in %s") % os.path.basename(path))
        # renderer that uses this mesh
        self.smr_obj = self.smr = None
        for o in objs:
            if o.type.name == "SkinnedMeshRenderer":
                d = o.read_typetree()
                if d.get("m_Mesh", {}).get("m_PathID") == self.mesh_obj.path_id:
                    self.smr_obj = o; self.smr = d; break
        if self.smr is None:
            raise ValueError(_tr("no body mesh found in %s") % os.path.basename(path))
        # bone index -> name
        tmap = {o.path_id: o.read_typetree() for o in objs if o.type.name == "Transform"}
        gname = {o.path_id: o.read_typetree().get("m_Name")
                 for o in objs if o.type.name == "GameObject"}
        self.bones = []
        for b in self.smr["m_Bones"]:
            td = tmap.get(b.get("m_PathID"))
            self.bones.append(gname.get(td.get("m_GameObject", {}).get("m_PathID")) if td else None)
        # material + textures
        self.mat_obj = self.by_pid.get(self.smr["m_Materials"][0]["m_PathID"])
        self.mat = self.mat_obj.read_typetree()
        self.tex = {}
        for te in self.mat["m_SavedProperties"]["m_TexEnvs"]:
            nm = te[0]; tpid = te[1]["m_Texture"]["m_PathID"]
            if tpid in self.by_pid:
                self.tex[nm] = self.by_pid[tpid]
        self._decode()

    def _decode(self):
        import numpy as np
        tt = self.tt
        n, st, off, order = _layout(tt)
        data = bytes(tt["m_VertexData"]["m_DataSize"])
        if len(data) < (off[order[-1]] + st[order[-1]]*n):
            raise ValueError("vertex data is external (m_StreamData) or compressed; "
                             "this model is not a plain uncompressed SIFAS body")
        self.n = n; self.st = st; self.off = off; self.order = order
        self.recs = {s: [data[off[s]+i*st[s]: off[s]+i*st[s]+st[s]] for i in range(n)]
                     for s in order}
        uv_s, uv_o = _uv_channel(tt)
        b0, s0 = off[0], st[0]
        self.uv_s, self.uv_o = uv_s, uv_o
        ub, us = off[uv_s], st[uv_s]
        b2, s2 = off[2], st[2]
        pos = np.zeros((n,3), np.float32); uv = np.zeros((n,2), np.float32)
        bw  = np.zeros((n,4), np.float32); bi = np.zeros((n,4), np.int32)
        for i in range(n):
            pos[i] = struct.unpack_from('<3f', data, b0+i*s0)
            uv[i]  = struct.unpack_from('<2f', data, ub+i*us+uv_o)
            bw[i]  = struct.unpack_from('<4f', data, b2+i*s2)
            bi[i]  = struct.unpack_from('<4i', data, b2+i*s2+16)
        self.pos, self.uv, self.bw, self.bi = pos, uv, bw, bi

    def tris(self):
        import numpy as np
        tt = self.tt
        ib = bytes(tt["m_IndexBuffer"])
        cnt = tt["m_SubMeshes"][0]["indexCount"]
        fmt = tt.get("m_IndexFormat", 0)
        return np.frombuffer(ib, '<u2' if fmt == 0 else '<u4', cnt).reshape(-1,3).astype(np.int64)

    def dom_names(self):
        import numpy as np
        dom = self.bi[np.arange(self.n), np.argmax(self.bw, 1)]
        return np.array([(self.bones[d] if 0 <= d < len(self.bones) else "") or "" for d in dom])

# --------------------------------------------------------------------------- #
#  helpers to rewrite a per-vertex record                                     #
# --------------------------------------------------------------------------- #
def _set_uv(rec, off, u, v):
    r = bytearray(rec); struct.pack_into('<2f', r, off, u, v); return bytes(r)
def _set_bones(rec, idx4):
    r = bytearray(rec); struct.pack_into('<4i', r, 16, *idx4); return bytes(r)

def _encode_vd(n, st, order, recs):
    out = bytearray()
    for s in order:
        blk = bytearray()
        for i in range(n):
            blk += recs[s][i]
        while len(blk) % 16:
            blk += b'\x00'
        out += blk
    return bytes(out)

# --------------------------------------------------------------------------- #
#  Coincident-ring seam finder                                                 #
# --------------------------------------------------------------------------- #
def _coincidence(posT, regT, posD, regD, h, half=0.025, eps=0.002):
    """Fraction of target region verts in the band [h-half,h+half] that have a
    near-coincident donor region vert. ~1.0 => a clean seam ring at height h."""
    import numpy as np
    selT = regT & (posT[:,1] >= h-half) & (posT[:,1] < h+half)
    if selT.sum() == 0:
        return 0.0, 0
    dl = posD[regD]
    if len(dl) == 0:
        return 0.0, 0
    hit = 0
    for p in posT[selT]:
        if np.min(np.abs(dl - p).sum(1)) < eps*3:   # cheap L1 prefilter
            if np.min(np.linalg.norm(dl - p, axis=1)) < eps:
                hit += 1
    n = int(selT.sum())
    return hit / n, n

def _snap_cut(posT, regT, posD, regD, y, search=0.08, step=0.01):
    """Snap a requested cut height y to a nearby vertex-coincident ring so the
    graft boundary lines up exactly.  Among rings with high coincidence, prefer
    the one CLOSEST to the requested height (keeps the seam where the user asked,
    i.e. tucked under the skirt)."""
    import numpy as np
    if y <= -1e8 or y >= 1e8:
        return y, 1.0
    cand = []
    h = y - search
    while h <= y + search + 1e-9:
        frac, n = _coincidence(posT, regT, posD, regD, h)
        if n >= 4:
            cand.append((round(h, 4), frac))
        h += step
    if not cand:
        return y, 0.0
    fmax = max(f for _h, f in cand)
    if fmax <= 0:
        return y, 0.0
    good = [(h, f) for h, f in cand if f >= fmax - 1e-6]
    good.sort(key=lambda hf: abs(hf[0] - y))   # closest to requested height
    return good[0]

def _components(pos, tris, n):
    """Union-find connected components, welding vertices that share a position
    (SIFAS splits seams into coincident verts)."""
    import numpy as np
    key2c = {}; canon = np.arange(n)
    for i in range(n):
        k = (round(float(pos[i,0]),4), round(float(pos[i,1]),4), round(float(pos[i,2]),4))
        c = key2c.get(k)
        if c is None: key2c[k] = i
        else: canon[i] = c
    parent = list(range(n))
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    for t in tris:
        a, b, c = int(canon[t[0]]), int(canon[t[1]]), int(canon[t[2]])
        ra, rb, rc = find(a), find(b), find(c)
        if ra != rb: parent[ra] = rb
        if find(b) != rc: parent[find(b)] = rc
    return np.array([find(int(canon[i])) for i in range(n)])

def skin_vertex_mask(pos, tris, dom_names, n):
    """True for vertices that belong to a BODY-SKIN connected component (one whose
    vertices are all weighted to anatomy bones).  Costume components (skirt, sash,
    ribbons, garters — anything with a non-anatomy bone) are False, so the graft
    never cuts into them."""
    import numpy as np
    comp = _components(pos, tris, n)
    is_anat = np.array([nm in ANATOMY for nm in dom_names])
    bad = set(comp[~is_anat].tolist())          # components containing costume bones
    return ~np.isin(comp, list(bad)) if bad else np.ones(n, bool)

CAP_BONES = {"Hips", "HipsSize"}   # the fake-skirt-bottom cap rides on the body hip bones
def _open_cap(pos, tris, dom_names, lift, edge_lift=0.0,
              ymin=0.60, ymax=0.95, rmax_lim=0.22, flat_tol=0.012):
    """Find the flat downward-facing disk (the fake skirt-bottom cap) and return
    (vertex indices, raised Y) that turn it into an open dome.  STRICT detection:
    a cap face must (a) face down, (b) be near-horizontal/flat, (c) have ALL three
    verts on a body HIP bone (Hips/HipsSize) — never a skirt/costume bone — and
    (d) sit near the body centre.  This stops skirt undersides (SkirtX_Dyna) being
    mistaken for the cap.  Centre rises by `lift`, outer rim by `edge_lift`."""
    import numpy as np
    if len(tris) == 0:
        return np.array([], int), np.array([])
    on_hip = np.isin(dom_names, list(CAP_BONES))
    fy = pos[tris, 1]
    flat = (fy.max(1) - fy.min(1)) < flat_tol            # the face itself is flat
    v0 = pos[tris[:,0]]; v1 = pos[tris[:,1]]; v2 = pos[tris[:,2]]
    fn = np.cross(v1-v0, v2-v0); nl = np.linalg.norm(fn, axis=1); nl[nl==0]=1; fn/=nl[:,None]
    cy = pos[tris,1].mean(1); cr = np.sqrt(pos[tris,0].mean(1)**2 + pos[tris,2].mean(1)**2)
    cap = ((fn[:,1] < -0.7) & flat & on_hip[tris].all(1)
           & (cy > ymin) & (cy < ymax) & (cr < rmax_lim))
    if cap.sum() == 0:
        return np.array([], int), np.array([])
    cv = np.unique(tris[cap])
    cv = cv[on_hip[cv]]                                   # belt-and-braces: hip-bone verts only
    if len(cv) == 0:
        return np.array([], int), np.array([])
    yp = np.median(pos[cv, 1])
    disk = cv[np.abs(pos[cv,1] - yp) < 0.02]
    rr = np.sqrt(pos[disk,0]**2 + pos[disk,2]**2)
    rm = rr.max() if rr.max() > 0 else 1.0
    t = np.clip(1 - rr/rm, 0, 1); t = t*t*(3-2*t)     # smoothstep, 1=centre 0=rim
    raise_ = edge_lift + (lift - edge_lift) * t        # rim->edge_lift, centre->lift
    return disk, pos[disk,1] + raise_

# --------------------------------------------------------------------------- #
#  Core graft                                                                  #
# --------------------------------------------------------------------------- #
def graft_one(target_path, donor_path, out_path, cut_low=-INF, cut_high=INF,
              region="lower", weld=True, open_cap_lift=0.0, open_cap_edge=0.0,
              exclude_accessories=True, gutter_px=4, merge_rim=True, mipmaps=True,
              dry_run=False, log=print):
    """Graft donor body skin in the band [cut_low, cut_high] (world Y) onto the
    target.  `region` ("lower" / "lower_belly" / "central") bounds which bones
    may be replaced so arms/head are never touched.  When `weld` is on, cut_low
    is snapped to the nearest vertex-coincident ring so the seam lines up
    exactly (no flaps/gap)."""
    import numpy as np
    from PIL import Image
    from UnityPy.enums import TextureFormat
    up = _require_unitypy()

    # if the output is a folder, write into it using the target's filename
    if os.path.isdir(out_path):
        out_path = os.path.join(out_path, os.path.basename(target_path))

    bones = REGIONS.get(region, LOWER)
    T = BodyMesh(up.load(target_path), target_path)
    D = BodyMesh(up.load(donor_path), donor_path)
    # Donor and target may use DIFFERENT vertex layouts (e.g. donor has extra UV
    # channels).  We convert each donor vertex into the target's exact layout
    # channel-by-channel, so any layout combination works.
    Tloc = _chan_locs(T.tt); Dloc = _chan_locs(D.tt)
    if T.st != D.st:
        log("  note: donor/target vertex layouts differ (donor streams %s vs "
            "target %s) — converting donor verts to target format"
            % (D.st, T.st))
    for need in (0, 4, 12, 13):       # position, uv0, blendweight, blendindices
        if need not in Tloc or need not in Dloc:
            raise ValueError("missing required vertex channel %d in donor or target" % need)

    nmT, nmD = T.dom_names(), D.dom_names()
    trisT, trisD = T.tris(), D.tris()

    regTv = np.isin(nmT, list(bones))   # per-vertex region mask
    regDv = np.isin(nmD, list(bones))
    if weld and cut_low > -1e8:
        snapped, frac = _snap_cut(T.pos, regTv, D.pos, regDv, cut_low)
        log("  weld seam: cut_low %.3f -> %.3f  (ring coincidence %.0f%%)"
            % (cut_low, snapped, frac*100))
        cut_low = snapped

    cyT = T.pos[trisT, 1].mean(1); cyD = D.pos[trisD, 1].mean(1)
    regT = regTv; regD = regDv

    # TARGET: only cut into BODY-SKIN connected components, never costume pieces
    # (skirt, sash, ribbons, garters) even when they ride on Hips/HipsSize bones.
    skinT = skin_vertex_mask(T.pos, trisT, nmT, T.n)
    # ...and only islands that actually contain a LEG bone count as droppable
    # leg/body geometry.  A waist badge weighted only to Hips (no leg bone) is
    # a separate island with no costume bone, so skin_vertex_mask alone would
    # wrongly treat it as skin; the leg-bone test protects it.
    compT = _components(T.pos, trisT, T.n)
    legT = np.isin(nmT, list(LEG_BONES))
    leg_comps = set(compT[legT].tolist())
    legbody = np.isin(compT, list(leg_comps))   # verts whose island has a leg bone
    skinT = skinT & legbody
    # DONOR: take anatomy-weighted verts (buttocks/hip/thigh + the painted
    # swimsuit on them); skip donor costume-bone verts (ribbons/strings).
    skinD = np.isin(nmD, list(ANATOMY))
    # DONOR: keep only the MAIN body connected component, so SEPARATE accessory
    # blobs (a thigh dagger, garter rings, ankle cuffs — even ones weighted to
    # leg bones) are left behind.
    if exclude_accessories:
        compD = _components(D.pos, trisD, D.n)
        usedD0 = np.unique(trisD)
        from collections import Counter as _C
        main = _C(compD[usedD0].tolist()).most_common(1)[0][0]
        mainD = (compD == main)
        skinD = skinD & mainD
        log("  donor main body component = %d verts (separate accessories excluded)"
            % int(mainD.sum()))

    # protect the flat "fake skirt bottom" cap from being dropped (keep it; it can
    # be opened separately).  Detect it on the target before any change.
    # Detect the TARGET's flat cap and, IF requested, its raised Y — computed on
    # the target alone, BEFORE merging.  This is the key: only the target cap
    # moves; the donor panty/skin (added later) is never touched.
    cdisk, cnewy = _open_cap(T.pos, trisT, nmT, open_cap_lift, open_cap_edge)
    capset = set(int(i) for i in cdisk)
    cap_newy = {int(cdisk[i]): float(cnewy[i]) for i in range(len(cdisk))}
    capT = np.zeros(T.n, bool)
    if capset:
        capT[list(capset)] = True

    bandT = (cyT >= cut_low) & (cyT <= cut_high)
    bandD = (cyD >= cut_low) & (cyD <= cut_high)
    tdrop = (regT[trisT].sum(1) >= 2) & bandT & skinT[trisT].all(1) & (~capT[trisT].any(1))
    keepT = trisT[~tdrop]
    ttake = (regD[trisD].sum(1) >= 2) & skinD[trisD].all(1) & bandD
    takeD = trisD[ttake]

    if len(takeD) == 0:
        raise ValueError("nothing to graft in this range (region/cut too narrow?)")

    log("  target drop: %d tris   donor take: %d tris   (cap verts kept: %d)"
        % (int(tdrop.sum()), len(takeD), len(capset)))
    if dry_run:
        log("  [dry run] would graft donor lower body (%d tris) -> %s"
            % (len(takeD), os.path.basename(out_path)))
        return None

    # bone remap donor -> target by NAME
    name2t = {nm: i for i, nm in enumerate(T.bones) if nm}
    d2t = {i: name2t[nm] for i, nm in enumerate(D.bones) if nm in name2t}
    miss = sorted({D.bones[i] for i in np.unique(D.bi[np.unique(takeD)])
                   if 0 <= i < len(D.bones) and D.bones[i] not in name2t})
    if miss:
        log("  WARN donor bones missing in target (mapped to root): %s" % ", ".join(miss))

    usedD = np.unique(takeD)
    # All donor verts are ADDED (kept separate from target verts) so their donor
    # UVs stay in the donor atlas half — abutting, NOT merging, avoids texture
    # stretch across the atlas seam.  Because cut_low sits on a coincident ring,
    # the donor boundary verts land exactly on the target boundary verts, so the
    # two rings abut with no gap.  To hide the shading crease there, we copy the
    # target vertex NORMAL onto each coincident donor seam vertex.
    kept_verts = np.unique(keepT)
    tpos_key = {}
    if weld:
        for i in kept_verts:
            tpos_key[tuple(np.round(T.pos[int(i)], 4))] = int(i)
    remap = {int(v): T.n + i for i, v in enumerate(usedD)}
    seam_normal = {}       # donor vert -> target normal bytes
    _ns, _no = (Tloc[1][0], Tloc[1][1]) if 1 in Tloc else (0, 12)
    if weld:
        for v in usedD:
            v = int(v)
            tv = tpos_key.get(tuple(np.round(D.pos[v], 4)))
            if tv is not None and np.linalg.norm(D.pos[v] - T.pos[tv]) < 0.002:
                seam_normal[v] = T.recs[_ns][tv][_no:_no+12]
        log("  seam ring: %d coincident verts abutted (normals matched)"
            % len(seam_normal))

    # atlas halves + UV remap (left = target, right = donor)
    MW = 2048
    g = gutter_px / MW
    def uL(u): return u * (0.5 - g)
    def uR(u): return 0.5 + g + u * (0.5 - g)

    newrec = {s: [] for s in T.order}
    uv_s, uv_o = T.uv_s, T.uv_o
    for i in range(T.n):
        for s in T.order:
            if s == uv_s:
                newrec[s].append(_set_uv(T.recs[s][i], uv_o, uL(T.uv[i,0]), T.uv[i,1]))
            else:
                newrec[s].append(T.recs[s][i])
    # channel-by-channel conversion of a donor vertex into the TARGET layout
    bw_s, bw_o = Tloc[12][0], Tloc[12][1]   # blendweight  stream/offset in target
    bi_s, bi_o = Tloc[13][0], Tloc[13][1]   # blendindices stream/offset in target
    nrm_s, nrm_o = (Tloc[1][0], Tloc[1][1]) if 1 in Tloc else (0, 12)  # normal loc
    def convert_donor(v):
        rec = {s: bytearray(T.st[s]) for s in T.order}
        for ci, (ts, to, tf, td, tsz) in Tloc.items():
            d = Dloc.get(ci)
            if d is not None and d[2] == tf and d[4] == tsz:   # same format+size
                ds, do = d[0], d[1]
                rec[ts][to:to+tsz] = D.recs[ds][v][do:do+tsz]
            # else: leave zero (donor lacks this channel / format differs)
        return rec
    dropped_infl = 0
    for v in usedD:
        v = int(v)
        rec = convert_donor(v)
        struct.pack_into('<2f', rec[uv_s], uv_o, uR(D.uv[v,0]), D.uv[v,1])  # uv0 -> donor atlas half
        # --- re-skin to BODY bones only -----------------------------------
        # A donor body vertex can carry secondary influences from costume bones
        # (e.g. SkirtA1_Dyna near the hip).  If kept, the grafted skin would
        # follow the target's skirt physics and poke out.  So drop every
        # non-anatomy influence and renormalise onto the anatomy bones.
        w = list(struct.unpack_from('<4f', rec[bw_s], bw_o))
        di = list(struct.unpack_from('<4i', rec[bi_s], bi_o))   # donor bone indices
        nw = [0.0,0.0,0.0,0.0]; ni = [0,0,0,0]; k = 0
        for wi, dvi in zip(w, di):
            dn = D.bones[dvi] if 0 <= dvi < len(D.bones) else None
            if wi > 0 and dn in ANATOMY and dn in name2t:
                nw[k] = wi; ni[k] = name2t[dn]; k += 1
            elif wi > 0 and dn not in ANATOMY:
                dropped_infl += 1
        s = sum(nw)
        if s > 0:
            nw = [x/s for x in nw]
        else:                                   # vertex was entirely costume-weighted
            nw = [1.0,0.0,0.0,0.0]; ni = [d2t.get(int(di[0]), 0),0,0,0]
        struct.pack_into('<4f', rec[bw_s], bw_o, *nw)
        struct.pack_into('<4i', rec[bi_s], bi_o, *ni)
        if v in seam_normal:
            rec[nrm_s][nrm_o:nrm_o+12] = seam_normal[v]                  # match seam normal
        for s in T.order:
            newrec[s].append(bytes(rec[s]))
    if dropped_infl:
        log("  dropped %d costume-bone influences from grafted body verts "
            "(re-skinned to body bones only)" % dropped_infl)

    takeR = np.vectorize(lambda v: remap[int(v)])(takeD)
    newtris = np.vstack([keepT, takeR]).astype(np.int64)
    allpos = np.vstack([T.pos, D.pos[usedD]])

    # compact unused vertices
    used = np.unique(newtris)
    o2n = {int(o): i for i, o in enumerate(used)}
    newrec = {s: [newrec[s][int(o)] for o in used] for s in T.order}
    newtris = np.vectorize(lambda v: o2n[int(v)])(newtris)
    allpos = allpos[used]
    nNew = len(used)

    # OPEN the flat "fake-skirt-bottom" cap by raising ONLY the target cap verts
    # detected earlier (mapped through compaction).  The donor panty/skin is left
    # exactly where it is — it is never part of cap_newy.
    if (open_cap_lift > 0 or open_cap_edge > 0) and cap_newy:
        moved = 0
        for orig, yv in cap_newy.items():
            ni = o2n.get(int(orig))
            if ni is None:
                continue
            r = bytearray(newrec[0][ni])
            struct.pack_into('<f', r, 4, float(yv))   # Y is float at offset 4 (after X)
            newrec[0][ni] = bytes(r)
            allpos[ni, 1] = yv
            moved += 1
        log("  opened skirt cap: raised %d TARGET cap verts (centre %.3f, edge %.3f)"
            % (moved, open_cap_lift, open_cap_edge))

    # build the combined atlas(es) and inject into the TARGET textures.
    # CRITICAL: paste each source into the EXACT pixel rectangle that uL()/uR()
    # map to, so UVs land precisely (the old code pasted full-width and the UVs
    # were ~gutter px off, shifting patterned regions).  A small gutter band is
    # filled by replicating the edge columns so bilinear/mip can't bleed across.
    def _pow2(x):
        p = 1
        while p < x:
            p <<= 1
        return p
    def combine(slot):
        # SIZE-ADAPTIVE: donor and target may have different texture sizes (e.g.
        # _MainTex 1024 vs 2048, _RimlightTex 512 vs 256).  Size each atlas HALF
        # to the LARGER of the two sources so the bigger texture keeps its
        # resolution (the old code crammed everything into a fixed 1024/512 half,
        # downscaling anything larger).  Dimensions are snapped to power-of-two
        # because every SIFAS texture is pow2 and NPOT + mipmaps misbehaves on
        # the game's mobile GLES targets.  The UV halves are FRACTIONAL (uL/uR
        # use g, not pixels), so each source just has to land in the exact pixel
        # rectangle its UVs map to; the gutter's sub-pixel shave is unchanged.
        ti0 = T.tex[slot].read().image.convert("RGBA")
        di0 = D.tex[slot].read().image.convert("RGBA")
        side = _pow2(max(ti0.width, di0.width))      # per-side width (pow2)
        H = _pow2(max(ti0.height, di0.height))       # atlas height  (pow2)
        W = side * 2                                  # total width   (pow2)
        fw = max(1, int(round((0.5 - g) * W)))       # target (left) content width
        ds = int(round((0.5 + g) * W))               # donor-half start x (== uR(0)*W)
        dw = W - ds                                  # donor (right) content width
        ti = ti0.resize((fw, H))
        di = di0.resize((dw, H))
        c = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        c.paste(ti, (0, 0)); c.paste(di, (ds, 0))
        # dilate into the centre gutter to stop seam bleed
        if ds > fw:
            right_col = ti.crop((fw - 1, 0, fw, H))
            left_col = di.crop((0, 0, 1, H))
            for x in range(fw, ds):
                c.paste(right_col if (x - fw) < (ds - fw) // 2 else left_col, (x, 0))
        return c
    slots = ["_MainTex"]
    if merge_rim and "_RimlightTex" in T.tex and "_RimlightTex" in D.tex:
        slots.append("_RimlightTex")
    for slot in slots:
        img = combine(slot)
        mc = int(math.floor(math.log2(max(img.size)))) + 1 if mipmaps else 1
        tex = T.tex[slot].read()
        tex.set_image(img, target_format=TextureFormat.RGBA32, mipmap_count=mc)
        tex.save()
        log("  atlas %s: %dx%d (mips=%d)" % (slot, img.width, img.height,
                                             getattr(tex, "m_MipCount", mc)))

    # write mesh
    tt = T.tt
    use32 = nNew > 65535
    tt["m_VertexData"]["m_VertexCount"] = nNew
    tt["m_VertexData"]["m_DataSize"] = _encode_vd(nNew, T.st, T.order, newrec)
    idx = newtris.reshape(-1)
    tt["m_IndexBuffer"] = idx.astype('<u4').tobytes() if use32 else idx.astype('<u2').tobytes()
    tt["m_IndexFormat"] = 1 if use32 else 0
    sm = tt["m_SubMeshes"][0]
    sm.update(firstByte=0, baseVertex=0, firstVertex=0, vertexCount=nNew, indexCount=len(idx))
    mn = allpos.min(0); mx = allpos.max(0); c = (mn+mx)/2; e = (mx-mn)/2
    aabb = {"m_Center": {"x": float(c[0]), "y": float(c[1]), "z": float(c[2])},
            "m_Extent": {"x": float(e[0]), "y": float(e[1]), "z": float(e[2])}}
    tt["m_LocalAABB"] = aabb
    if isinstance(sm.get("localAABB"), dict):
        sm["localAABB"] = aabb
    T.mesh_obj.save_typetree(tt)

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(T.env.file.save(packer="original"))
    log(_tr("Saved: %s") % out_path)
    log("  verts %d -> %d   tris %d -> %d" % (T.n, nNew, len(trisT), len(newtris)))
    return out_path

# --------------------------------------------------------------------------- #
#  Batch                                                                       #
# --------------------------------------------------------------------------- #
def iter_bundles(folder):
    for root, _dirs, files in os.walk(folder):
        for fn in files:
            if fn.lower().endswith((".meta", ".png", ".txt", ".zip")):
                continue
            yield os.path.join(root, fn)

def run_batch(donor, folder, out_root=None, **kw):
    log = kw.get("log", print)
    out_root = out_root or os.path.join(sukusta_dir(), "modded")
    ok = fail = 0
    for tgt in iter_bundles(folder):
        if os.path.abspath(tgt) == os.path.abspath(donor):
            continue
        rel = os.path.relpath(tgt, folder)
        out = os.path.join(out_root, rel)
        try:
            log("• %s" % rel)
            graft_one(tgt, donor, out, **kw)
            ok += 1
        except Exception as e:
            fail += 1
            log("  skip (%s)" % e)
    log("batch done: %d ok, %d skipped" % (ok, fail))

# --------------------------------------------------------------------------- #
#  CLI                                                                         #
# --------------------------------------------------------------------------- #
def _num(value, default):
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        raise SystemExit("invalid height '%s' (need a number)" % value)

def main_cli(argv):
    p = argparse.ArgumentParser(description="SIFAS lower-body skin graft (atlas merge)")
    p.add_argument("--donor", required=True, help="model with a good lower body")
    p.add_argument("--target", help="model to fix (single file)")
    p.add_argument("--batch", help="folder of targets (one donor -> all)")
    p.add_argument("--out", help="output file (single) or folder (batch)")
    p.add_argument("--cut", default="hip_fix",
                   help="band preset: %s (default hip_fix)" % "/".join(CUT_PRESETS))
    p.add_argument("--cut-low",
                   help="explicit band BOTTOM Y, overrides --cut "
                        "(approx: ankle 0.11, mid-calf 0.30, knee 0.50, "
                        "mid-thigh 0.67, crotch 0.85, waist 1.05)")
    p.add_argument("--cut-high",
                   help="explicit band TOP Y, overrides --cut "
                        "(approx: knee 0.50, gluteal-fold 0.80, crotch 0.85, "
                        "lower-belly 0.92, waist 1.05, chest 1.25; blank=no limit)")
    p.add_argument("--region", default="lower", choices=list(REGIONS),
                   help="bones allowed to change (default lower)")
    p.add_argument("--no-weld", action="store_true",
                   help="do not snap the cut to a coincident ring")
    p.add_argument("--keep-accessories", action="store_true",
                   help="keep donor separate accessory blobs (dagger/garter); default excludes them")
    p.add_argument("--open-cap", type=float, default=0.0, metavar="LIFT",
                   help="open the flat fake-skirt-bottom by raising its CENTRE "
                        "by LIFT (e.g. 0.08); 0 = off (cap kept flat)")
    p.add_argument("--open-cap-edge", type=float, default=0.0, metavar="LIFT",
                   help="also raise the cap's OUTER RIM by this much (e.g. 0.02)")
    p.add_argument("--gutter", type=int, default=4, help="atlas gutter in px")
    p.add_argument("--no-rim", action="store_true", help="do not merge the rim map")
    p.add_argument("--no-mipmaps", action="store_true", help="do not build mipmaps")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args(argv)
    pre_low, pre_high = CUT_PRESETS.get(a.cut, (None, None))
    if pre_low is None and a.cut_low is None:
        a.cut_low = a.cut  # allow --cut <number>
        pre_low, pre_high = -INF, INF
    cut_low = _num(a.cut_low, pre_low)
    cut_high = _num(a.cut_high, pre_high)
    kw = dict(cut_low=cut_low, cut_high=cut_high, region=a.region,
              weld=not a.no_weld, open_cap_lift=a.open_cap, open_cap_edge=a.open_cap_edge,
              exclude_accessories=not a.keep_accessories,
              gutter_px=a.gutter, merge_rim=not a.no_rim, mipmaps=not a.no_mipmaps,
              dry_run=a.dry_run)
    if a.batch:
        run_batch(a.donor, a.batch, a.out, **kw)
    elif a.target:
        out = a.out or default_modded_path(a.target)
        graft_one(a.target, a.donor, out, **kw)
    else:
        raise SystemExit("give --target FILE or --batch FOLDER")

# --------------------------------------------------------------------------- #
#  Text menu (no display / Termux)                                            #
# --------------------------------------------------------------------------- #
def main_menu():
    print("=== %s ===" % _tr("SIFAS Lower-Body Swap"))
    donor = input(_tr("Donor (good lower body):") + " ").strip()
    target = input(_tr("Target (broken / to fix):") + " ").strip()
    print(_tr("Replace range (cut):"))
    for i, (k, lbl) in enumerate(CUT_LABELS):
        print("  %d) %s" % (i+1, _tr(lbl)))
    sel = input("> ").strip() or "1"
    try:
        key = CUT_LABELS[int(sel)-1][0]
    except Exception:
        key = "hip_fix"
    cut_low, cut_high = CUT_PRESETS.get(key, (-INF, INF))
    if key == "custom":
        print(_tr("  height guide: ankle 0.11 / mid-calf 0.30 / knee 0.50 / "
                  "mid-thigh 0.67 / crotch 0.85 / lower-belly 0.92 / waist 1.05"))
        cut_low = _num(input("  low Y (bottom, blank=feet): ").strip() or None, -INF)
        cut_high = _num(input("  high Y (top, blank=no limit): ").strip() or None, INF)
    out = input(_tr("Output file / folder:") + " ").strip() or default_modded_path(target)
    graft_one(target, donor, out, cut_low=cut_low, cut_high=cut_high)

# --------------------------------------------------------------------------- #
#  GUI (tkinter)                                                               #
# --------------------------------------------------------------------------- #
def main_gui():
    import threading, queue
    import tkinter as tk
    from tkinter import ttk, filedialog
    root = tk.Tk()
    root.title(_tr("SIFAS Lower-Body Swap"))
    q = queue.Queue()

    def row(r, label):
        ttk.Label(root, text=_tr(label)).grid(row=r, column=0, sticky="w", padx=6, pady=3)
        e = ttk.Entry(root, width=52); e.grid(row=r, column=1, padx=4, pady=3)
        return e

    donor_e = row(0, "Donor (good lower body):")
    target_e = row(1, "Target (broken / to fix):")
    out_e = row(2, "Output file / folder:")

    def browse(entry, folder=False):
        path = filedialog.askdirectory() if folder else filedialog.askopenfilename()
        if path:
            entry.delete(0, "end"); entry.insert(0, path)
    ttk.Button(root, text=_tr("Browse…"), command=lambda: browse(donor_e)).grid(row=0, column=2, padx=4)
    batch_var = tk.BooleanVar()
    ttk.Button(root, text=_tr("Browse…"),
               command=lambda: browse(target_e, batch_var.get())).grid(row=1, column=2, padx=4)
    ttk.Button(root, text=_tr("Browse…"),
               command=lambda: browse(out_e, True)).grid(row=2, column=2, padx=4)

    ttk.Label(root, text=_tr("Replace range (cut):")).grid(row=3, column=0, sticky="w", padx=6)
    cut_box = ttk.Combobox(root, state="readonly",
                           values=[_tr(lbl) for _k, lbl in CUT_LABELS])
    cut_box.current(0); cut_box.grid(row=3, column=1, sticky="we", padx=4)

    # custom band: low / high Y + region (used when "custom range…" is picked)
    cust = ttk.Frame(root); cust.grid(row=4, column=1, sticky="w")
    ttk.Label(cust, text=_tr("Custom band  low Y:")).pack(side="left")
    low_e = ttk.Entry(cust, width=7); low_e.pack(side="left", padx=2)
    ttk.Label(cust, text=_tr("high Y:")).pack(side="left")
    high_e = ttk.Entry(cust, width=7); high_e.pack(side="left", padx=2)
    ttk.Label(cust, text=_tr("region:")).pack(side="left", padx=(8,0))
    region_box = ttk.Combobox(cust, state="readonly", width=12, values=list(REGIONS))
    region_box.current(0); region_box.pack(side="left")
    # height reference so a typed cut Y is easy to place on the body
    ttk.Label(root, foreground="#888",
              text=_tr("Y guide: ankle .11 · calf .30 · knee .50 · thigh .67 "
                       "· crotch .85 · belly .92 · waist 1.05")
              ).grid(row=10, column=1, columnspan=2, sticky="w", padx=4)

    capf = ttk.Frame(root); capf.grid(row=9, column=1, sticky="w")
    ttk.Label(capf, text=_tr("Open skirt cap lift (0=off):")).pack(side="left")
    cap_e = ttk.Entry(capf, width=6); cap_e.insert(0, "0"); cap_e.pack(side="left", padx=2)
    ttk.Label(capf, text=_tr("edge:")).pack(side="left")
    cape_e = ttk.Entry(capf, width=6); cape_e.insert(0, "0"); cape_e.pack(side="left", padx=2)

    rim_var = tk.BooleanVar(value=True)
    mip_var = tk.BooleanVar(value=True)
    dry_var = tk.BooleanVar(value=False)
    acc_var = tk.BooleanVar(value=False)   # keep donor accessories? default no
    ttk.Checkbutton(root, text=_tr("Batch (target is a folder)"), variable=batch_var).grid(row=5, column=1, sticky="w")
    ttk.Checkbutton(root, text=_tr("Merge rim map too"), variable=rim_var).grid(row=6, column=1, sticky="w")
    ttk.Checkbutton(root, text=_tr("Generate mipmaps"), variable=mip_var).grid(row=7, column=1, sticky="w")
    ttk.Checkbutton(root, text=_tr("Dry run (no write)"), variable=dry_var).grid(row=8, column=1, sticky="w")
    ttk.Checkbutton(root, text=_tr("Keep donor accessories (dagger/garter)"), variable=acc_var).grid(row=8, column=2, sticky="w")

    log = tk.Text(root, height=12, width=74); log.grid(row=11, column=0, columnspan=3, padx=6, pady=6)
    def put(msg): q.put(msg)

    def work():
        try:
            donor = donor_e.get().strip(); target = target_e.get().strip()
            if not donor or not target:
                put(_tr("Pick a donor and a target first.")); return
            key = CUT_LABELS[cut_box.current()][0]
            region = "lower"
            if key == "custom":
                cut_low = _num(low_e.get().strip() or None, -INF)
                cut_high = _num(high_e.get().strip() or None, INF)
                region = region_box.get() or "lower"
            else:
                cut_low, cut_high = CUT_PRESETS.get(key, (-INF, INF))
            kw = dict(cut_low=cut_low, cut_high=cut_high, region=region,
                      open_cap_lift=_num(cap_e.get().strip() or None, 0.0),
                      open_cap_edge=_num(cape_e.get().strip() or None, 0.0),
                      exclude_accessories=not acc_var.get(),
                      merge_rim=rim_var.get(), mipmaps=mip_var.get(),
                      dry_run=dry_var.get(), log=put)
            put(_tr("Working…"))
            if batch_var.get():
                run_batch(donor, target, out_e.get().strip() or None, **kw)
            else:
                out = out_e.get().strip() or default_modded_path(target)
                graft_one(target, donor, out, **kw)
            put(_tr("Done."))
        except Exception as e:
            put(_tr("ERROR: %s") % e)
            put(traceback.format_exc())

    def run():
        threading.Thread(target=work, daemon=True).start()
    ttk.Button(root, text=_tr("Run"), command=run).grid(row=10, column=1, pady=4)

    # language selector
    ttk.Label(root, text=_tr("Language:")).grid(row=12, column=0, sticky="w", padx=6)
    lang_var = tk.StringVar(value=dict(_LANG_NAMES)[_LANG.lang])
    def on_lang(_e=None):
        for code, name in _LANG_NAMES:
            if name == lang_var.get():
                _LANG.set(code)
        root.destroy(); main_gui()
    lb = ttk.Combobox(root, textvariable=lang_var, state="readonly",
                      values=[n for _c, n in _LANG_NAMES]); lb.grid(row=12, column=1, sticky="w")
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
