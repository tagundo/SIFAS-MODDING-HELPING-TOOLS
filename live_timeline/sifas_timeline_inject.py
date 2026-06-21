#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sifas_timeline_inject — SIFAS 라이브 멤버 타임라인 주입 (입 + 표정, CLI + GUI)
============================================================================

SIFAC 라이브 데이터를 SIFAS 라이브 번들의 멤버 타임라인에 UnityPy TypeTree 로
**직접 기입**합니다. 입(립싱크)과 표정(눈/시선/볼)을 한 도구로 묶었습니다.

서브커맨드:
    lip   SCD 가사 → MemberLipSyncTrack("Mouth")
    face  표정 스크립트 / 자동 눈깜빡임 → MemberEye/Gaze/CheekTrack
    gui   세 탭(입·표정·카메라) GUI 실행  (카메라 탭은 noesis-llsifac/tools 호출)

  # 입: SIFAC 음소 코드 [들어오는모음][자음][목표모음] → 마지막 모음이 입모양
  #     (oto→O, usu→U, ete→E). 화이트리스트 없이 미지 코드 0%.
  # 입모양 테이블(실번들 확인): A=1 I=2 U=3 E=4 O=5 N=6  (E2=13, Laugh=8)
  # 표정 테이블(실번들 확인):
  #   Eye : Close=1 Closish=2 Open=3 WideOpen=4 Close_Smile=5
  #         WinkR=12 WinkL=13 Trouble=14 Sad=15 Angry=16 Missing=18  (+weight)
  #   Gaze: Camera=21 Audience=22 Up=31 Down=32 Left=33 Right=34   (+weightForDirection)
  #   Cheek: Ppo (볼터치)

예:
    python3 sifas_timeline_inject.py lip  --scd lyrics.scd --bundle live.unity --out o.unity --weight 1.0
    python3 sifas_timeline_inject.py face --script faces.txt --auto-blink --bundle live.unity --out o.unity
    python3 sifas_timeline_inject.py face --list-names
    python3 sifas_timeline_inject.py gui        # (인자 없이 실행해도 GUI)

UnityPy 필요(pip install UnityPy). tkinter 는 GUI 실행 시에만 필요(표준 라이브러리).
"""

from __future__ import annotations
import argparse
import json
import math
import random
import struct
import sys
from collections import Counter
from pathlib import Path

# =========================================================================== #
# 입 (립싱크)
# =========================================================================== #
VOWEL = {"a": "A", "i": "I", "u": "U", "e": "E", "o": "O"}
SHAPE_INDEX = {"A": 1, "I": 2, "U": 3, "E": 4, "O": 5, "N": 6, "E2": 13, "Laugh": 8}

SCD_MAGIC = b"Scor"
_ENTRY = 32
_HDR = 64


def reduce_phoneme(code: str):
    """SIFAC 음소 코드 → SIFAS 입모양(A/I/U/E/O/N) 또는 None(무음/미지)."""
    c = (code or "").strip().lower()
    if not c:
        return None
    if c in ("nn", "n"):
        return "N"
    for ch in reversed(c):          # 마지막 모음 = 입모양
        if ch in VOWEL:
            return VOWEL[ch]
    return None


def parse_scd(path: Path, char=None, offset=0.0):
    """SIFAC score_*_lyrics_*.scd → [(start_s, dur_s, shape, raw_code), ...]."""
    data = Path(path).read_bytes()
    if data[:4] != SCD_MAGIC:
        raise ValueError(f"not a Scor SCD: {path}")
    count = struct.unpack_from("<I", data, 8)[0]
    count = min(count, (len(data) - _HDR) // _ENTRY)

    rows, charcount = [], Counter()
    for i in range(count):
        off = _HDR + i * _ENTRY
        start = struct.unpack_from("<I", data, off + 4)[0]
        dur = struct.unpack_from("<I", data, off + 16)[0]
        cid = data[off + 20]
        phon = data[off + 21:off + 24].decode("ascii", "ignore").replace("\x00", "").strip()
        if phon:
            rows.append((cid, start, dur, phon))
            charcount[cid] += 1
    if not rows:
        return [], None, charcount
    if char is None:
        char = charcount.most_common(1)[0][0]

    entries = []
    for cid, start, dur, phon in rows:
        if cid != char:
            continue
        shape = reduce_phoneme(phon)
        if shape is None:
            continue
        entries.append((start / 1000.0 + offset, max(dur / 1000.0, 0.04), shape, phon))
    entries.sort(key=lambda e: e[0])
    return entries, char, charcount


def inject_lip(bundle_in: Path, entries, bundle_out: Path, weight=None,
               track_name=None, dry_run=False, verbose=True):
    import UnityPy
    env = UnityPy.load(str(bundle_in))
    objs = list(env.objects)
    smap = {o.path_id: o.read().m_Name for o in objs if o.type.name == "MonoScript"}

    def scls(t):
        return smap.get(t.get("m_Script", {}).get("m_PathID"))

    mb = {o.path_id: o for o in objs if o.type.name == "MonoBehaviour"}
    tracks = []
    for o in objs:
        if o.type.name != "MonoBehaviour":
            continue
        t = o.read_typetree()
        if scls(t) == "MemberLipSyncTrack" and (not track_name or t.get("m_Name") == track_name):
            tracks.append((o, t))
    if not tracks:
        raise RuntimeError("MemberLipSyncTrack not found in bundle")

    for o, t in tracks:
        clips = t.get("m_Clips", [])
        n_used = min(len(clips), len(entries))
        if verbose:
            print(f"[lip] '{t.get('m_Name')}'  clips={len(clips)} entries={len(entries)} "
                  f"-> writing {n_used}, parking {max(0, len(clips) - n_used)}")
        for i, clip in enumerate(clips):
            pa = mb.get(clip.get("m_Asset", {}).get("m_PathID"))
            if i < len(entries):
                s, d, shape, _ = entries[i]
                clip["m_Start"] = float(s); clip["m_Duration"] = float(d)
                clip["m_DisplayName"] = shape
                if pa is not None:
                    pt = pa.read_typetree()
                    if "index" in pt:
                        pt["index"] = SHAPE_INDEX.get(shape, 1)
                    if "weight" in pt and weight is not None:
                        pt["weight"] = float(weight)
                    if "paramName" in pt:
                        pt["paramName"] = "a"
                    if not dry_run:
                        pa.save_typetree(pt)
            else:
                clip["m_Duration"] = 0.0
                if pa is not None:
                    pt = pa.read_typetree()
                    if "weight" in pt:
                        pt["weight"] = 0.0
                    if not dry_run:
                        pa.save_typetree(pt)
        if not dry_run:
            o.save_typetree(t)

    if not dry_run:
        Path(bundle_out).parent.mkdir(parents=True, exist_ok=True)
        with open(bundle_out, "wb") as f:
            f.write(env.file.save(packer="lz4"))
        if verbose:
            print(f"[ok] wrote {bundle_out}")


# =========================================================================== #
# 표정 (눈 / 시선 / 볼)
# =========================================================================== #
EYE = {"Close": 1, "Closish": 2, "Open": 3, "WideOpen": 4, "Close_Smile": 5,
       "WinkR": 12, "WinkL": 13, "Trouble": 14, "Sad": 15, "Angry": 16, "Missing": 18}
GAZE = {"Camera": 21, "Audience": 22, "Up": 31, "Down": 32, "Left": 33, "Right": 34}
CHEEK = {"Ppo"}

TRACK_CLASS = {
    "eye":   ("MemberEyeTrack",   "index", EYE),
    "gaze":  ("MemberGazeTrack",  "target", GAZE),
    "cheek": ("MemberCheekTrack", None, None),
}
WEIGHT_FIELD = {"eye": "weight", "gaze": "weightForDirection", "cheek": "weight"}


class FaceEntry:
    __slots__ = ("track", "start", "dur", "name", "weight")

    def __init__(self, track, start, dur, name, weight):
        self.track, self.start, self.dur, self.name, self.weight = track, start, dur, name, weight


def _validate_face(track, name):
    table = {"eye": EYE, "gaze": GAZE, "cheek": CHEEK}[track]
    if name not in table:
        raise ValueError(f"unknown {track} '{name}'; valid: {', '.join(table)}")


def parse_script(path: Path):
    """표정 스크립트(텍스트) → [FaceEntry, ...].  한 줄: <track> <start> <dur> <name> [weight]"""
    entries = []
    for ln, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 4:
            raise ValueError(f"line {ln}: need '<track> <start> <dur> <name> [weight]': {raw!r}")
        track = parts[0].lower()
        if track not in TRACK_CLASS:
            raise ValueError(f"line {ln}: unknown track '{track}' (eye/gaze/cheek)")
        _validate_face(track, parts[3])
        weight = float(parts[4]) if len(parts) > 4 else 1.0
        entries.append(FaceEntry(track, float(parts[1]), float(parts[2]), parts[3], weight))
    return entries


def auto_blink(duration=125.0, period=3.5, jitter=1.2, blink=0.16, seed=0):
    """주기적 자연 눈깜빡임(Close) 엔트리 생성."""
    rng = random.Random(seed)
    t, out = 1.0, []
    while t < duration:
        out.append(FaceEntry("eye", round(t, 3), blink, "Close", 1.0))
        t += period + rng.uniform(-jitter, jitter)
    return out


def inject_face(bundle_in: Path, entries, bundle_out: Path, dry_run=False, verbose=True):
    import UnityPy
    env = UnityPy.load(str(bundle_in))
    objs = list(env.objects)
    smap = {o.path_id: o.read().m_Name for o in objs if o.type.name == "MonoScript"}

    def scls(t):
        return smap.get(t.get("m_Script", {}).get("m_PathID"))

    mb = {o.path_id: o for o in objs if o.type.name == "MonoBehaviour"}
    by_track = {"eye": [], "gaze": [], "cheek": []}
    for e in entries:
        by_track[e.track].append(e)
    for k in by_track:
        by_track[k].sort(key=lambda e: e.start)

    for kind, (cls, idx_field, table) in TRACK_CLASS.items():
        ents = by_track[kind]
        if not ents:
            continue
        track_objs = [o for o in objs if o.type.name == "MonoBehaviour"
                      and scls(o.read_typetree()) == cls]
        if not track_objs:
            if verbose:
                print(f"[warn] {cls} not in bundle; skipping {len(ents)} {kind} entries")
            continue
        o = track_objs[0]
        t = o.read_typetree()
        clips = t.get("m_Clips", [])
        wfield = WEIGHT_FIELD[kind]
        for i, clip in enumerate(clips):
            pa = mb.get(clip.get("m_Asset", {}).get("m_PathID"))
            if i < len(ents):
                e = ents[i]
                clip["m_Start"] = float(e.start); clip["m_Duration"] = float(e.dur)
                clip["m_DisplayName"] = e.name
                if pa is not None:
                    pt = pa.read_typetree()
                    if idx_field and idx_field in pt and table:
                        pt[idx_field] = table[e.name]
                    if wfield in pt:
                        pt[wfield] = float(e.weight)
                    if not dry_run:
                        pa.save_typetree(pt)
            else:
                clip["m_Duration"] = 0.0
                if pa is not None:
                    pt = pa.read_typetree()
                    if wfield in pt:
                        pt[wfield] = 0.0
                    if not dry_run:
                        pa.save_typetree(pt)
        if not dry_run:
            o.save_typetree(t)
        if verbose:
            print(f"[face] {cls}: wrote {min(len(clips), len(ents))}/{len(clips)} clips ({kind})")

    if not dry_run:
        Path(bundle_out).parent.mkdir(parents=True, exist_ok=True)
        with open(bundle_out, "wb") as f:
            f.write(env.file.save(packer="lz4"))
        if verbose:
            print(f"[ok] wrote {bundle_out}")


# =========================================================================== #
# 카메라 (SIFAC 카메라 JSON → SIFAS "Camera1" AnimationClip)
# =========================================================================== #
# SIFAS 카메라 = AnimationTrack "Camera1" 의 AnimationClip. 7커브 바인딩:
#   Transform.position(attr1) + Transform.euler(attr4) + LiveCoreCameraWork.FOV.
# 기존 카메라 클립 하나를 DenseClip 으로 덮어써 전곡을 커버, 나머지 컷은 길이 0.
# 회전: 쿼터니언 → Unity 오일러(ZXY). JSON 입력은 noesis 불필요(자기완결).
# .bscam → JSON 추출만 noesis sifac_camera.py 사용.

def quat_to_unity_euler(q):
    x, y, z, w = q
    n = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    x, y, z, w = x / n, y / n, z / n, w / n
    m12 = 2 * (y * z - w * x); m02 = 2 * (x * z + w * y); m22 = 1 - 2 * (x * x + y * y)
    m10 = 2 * (x * y + w * z); m11 = 1 - 2 * (x * x + z * z)
    m20 = 2 * (x * z - w * y); m00 = 1 - 2 * (y * y + z * z)
    sx = max(-1.0, min(1.0, -m12)); ex = math.asin(sx)
    if abs(sx) < 0.9999999:
        ey = math.atan2(m02, m22); ez = math.atan2(m10, m11)
    else:
        ey = math.atan2(-m20, m00); ez = 0.0
    return math.degrees(ex), math.degrees(ey), math.degrees(ez)


def _nlerp(qa, qb, t):
    d = sum(a * b for a, b in zip(qa, qb))
    if d < 0:
        qb = [-b for b in qb]
    q = [a + (b - a) * t for a, b in zip(qa, qb)]
    n = math.sqrt(sum(c * c for c in q)) or 1.0
    return [c / n for c in q]


def resample_60(frames, fps_out=60.0):
    """JSON frames(t,pos,rot,fov) → 60fps 균일 그리드."""
    if not frames:
        return []
    n = int(round(frames[-1]["t"] * fps_out)) + 1
    out, j = [], 0
    for i in range(n):
        t = i / fps_out
        while j + 1 < len(frames) and frames[j + 1]["t"] < t:
            j += 1
        f0 = frames[j]; f1 = frames[min(j + 1, len(frames) - 1)]
        span = (f1["t"] - f0["t"]) or 1.0
        a = max(0.0, min(1.0, (t - f0["t"]) / span))
        pos = [f0["pos"][k] + (f1["pos"][k] - f0["pos"][k]) * a for k in range(3)]
        rot = _nlerp(f0["rot"], f1["rot"], a)
        fov = f0["fov"] + (f1["fov"] - f0["fov"]) * a
        out.append((t, pos, rot, fov))
    return out


def build_sample_array(samples, scale=1.0, z_flip=False, yaw180=False):
    """samples → DenseClip flat float array [px,py,pz, ex,ey,ez, fov] × N."""
    arr = []
    for _t, pos, rot, fov in samples:
        px, py, pz = pos[0] * scale, pos[1] * scale, pos[2] * scale
        if z_flip:
            pz = -pz
        ex, ey, ez = quat_to_unity_euler(rot)
        if z_flip:
            ey = -ey; ez = -ez
        if yaw180:
            ey += 180.0
        arr.extend([px, py, pz, ex, ey, ez, float(fov)])
    return arr


def inject_camera(camera_json: Path, bundle_in: Path, bundle_out: Path,
                  scale=1.0, z_flip=False, yaw180=False, verbose=True):
    import UnityPy
    track = json.loads(Path(camera_json).read_text(encoding="utf-8"))
    samples = resample_60(track.get("frames", []))
    n = len(samples)
    if n == 0:
        raise ValueError("camera json has no frames")
    sample_array = build_sample_array(samples, scale=scale, z_flip=z_flip, yaw180=yaw180)
    stop_time = (n - 1) / 60.0

    env = UnityPy.load(str(bundle_in))
    objs = list(env.objects)
    smap = {o.path_id: o.read().m_Name for o in objs if o.type.name == "MonoScript"}

    def scls(t):
        return smap.get(t.get("m_Script", {}).get("m_PathID"))

    cam_track = None
    for o in objs:
        if o.type.name == "MonoBehaviour":
            t = o.read_typetree()
            if scls(t) == "AnimationTrack" and "camera" in str(t.get("m_Name", "")).lower():
                cam_track = (o, t); break
    if cam_track is None:
        for o in objs:
            if o.type.name == "MonoBehaviour" and scls(o.read_typetree()) == "AnimationTrack":
                cam_track = (o, o.read_typetree()); break
    if cam_track is None:
        raise RuntimeError("no AnimationTrack (Camera1) found in bundle")

    cam_clips = [o for o in objs
                 if o.type.name == "AnimationClip" and "camera" in o.read().m_Name.lower()]
    if not cam_clips:
        raise RuntimeError("no camera AnimationClip found in bundle")
    target = sorted(cam_clips, key=lambda o: o.read().m_Name)[0]
    ct = target.read_typetree()

    clip = ct["m_MuscleClip"]["m_Clip"]["data"]
    clip["m_StreamedClip"]["data"] = []; clip["m_StreamedClip"]["curveCount"] = 0
    dense = clip["m_DenseClip"]
    dense["m_FrameCount"] = n; dense["m_CurveCount"] = 7
    dense["m_SampleRate"] = 60.0; dense["m_BeginTime"] = 0.0
    dense["m_SampleArray"] = sample_array
    if isinstance(clip.get("m_ConstantClip"), dict):
        clip["m_ConstantClip"]["data"] = []
    ct["m_MuscleClip"]["m_StopTime"] = stop_time
    ct["m_MuscleClip"]["m_StartTime"] = 0.0
    ct["m_SampleRate"] = 60.0
    target.save_typetree(ct)

    o_tr, t_tr = cam_track
    clips = t_tr.get("m_Clips", [])
    set_main = False
    for c in clips:
        if not set_main and abs(float(c.get("m_Start", 0.0))) < 1e-6:
            c["m_Start"] = 0.0; c["m_Duration"] = stop_time; set_main = True
        else:
            c["m_Duration"] = 0.0
    if not set_main and clips:
        clips[0]["m_Start"] = 0.0; clips[0]["m_Duration"] = stop_time
        for c in clips[1:]:
            c["m_Duration"] = 0.0
    o_tr.save_typetree(t_tr)

    Path(bundle_out).parent.mkdir(parents=True, exist_ok=True)
    with open(bundle_out, "wb") as f:
        f.write(env.file.save(packer="lz4"))
    if verbose:
        fovs = [s[3] for s in samples]
        print(f"[cam] {n} samples @60fps ({stop_time:.2f}s) fov {min(fovs):.1f}..{max(fovs):.1f} "
              f"z_flip={z_flip} yaw180={yaw180} -> overwrote '{target.read().m_Name}'")
        print(f"[ok] wrote {bundle_out}")


# =========================================================================== #
# GUI (tkinter — 실행 시에만 import)
# =========================================================================== #
def _find_noesis_tools():
    here = Path(__file__).resolve().parent
    cands = [here.parent.parent / "noesis-llsifac" / "tools",
             here.parent.parent.parent / "noesis-llsifac" / "tools",
             here.parent / "noesis-llsifac" / "tools",
             Path.home() / "noesis-llsifac" / "tools"]
    for c in cands:
        if (c / "sifac_camera.py").is_file():   # .bscam → JSON 추출용(노에시스)
            return str(c)
    return None


def run_gui():
    import queue
    import threading
    import traceback
    from contextlib import redirect_stdout
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    class QW:
        def __init__(self, q): self.q = q
        def write(self, s):
            if s:
                self.q.put(s)
        def flush(self): pass

    class App:
        def __init__(self, root):
            self.root = root
            root.title("SIFAS 라이브 주입 (입 · 표정 · 카메라)")
            root.geometry("720x620")
            self.q = queue.Queue(); self.busy = False
            self.noesis = _find_noesis_tools()
            self.nb = ttk.Notebook(root)
            self.nb.pack(fill="both", expand=True, padx=8, pady=(8, 0))
            self._lip(ttk.Frame(self.nb, padding=10))
            self._face(ttk.Frame(self.nb, padding=10))
            self._cam(ttk.Frame(self.nb, padding=10))
            lf = ttk.LabelFrame(root, text="로그", padding=4)
            lf.pack(fill="both", expand=True, padx=8, pady=8)
            self.log = tk.Text(lf, height=12, wrap="word", state="disabled",
                               bg="#101014", fg="#d8d8d8")
            sb = ttk.Scrollbar(lf, command=self.log.yview)
            self.log.configure(yscrollcommand=sb.set)
            self.log.pack(side="left", fill="both", expand=True); sb.pack(side="right", fill="y")
            self.status = ttk.Label(root, text="준비됨", anchor="w")
            self.status.pack(fill="x", padx=10, pady=(0, 6))
            root.after(80, self._drain)

        def _row(self, p, r, label, var, save=False, types=(("All", "*.*"),)):
            ttk.Label(p, text=label).grid(row=r, column=0, sticky="w", pady=3)
            ttk.Entry(p, textvariable=var, width=58).grid(row=r, column=1, sticky="we", padx=4)

            def br():
                fn = filedialog.asksaveasfilename if save else filedialog.askopenfilename
                x = fn(filetypes=list(types))
                if x:
                    var.set(x)
            ttk.Button(p, text="…", width=3, command=br).grid(row=r, column=2)
            p.columnconfigure(1, weight=1)

        def _auto(self, bvar, ovar, suf):
            if bvar.get().strip() and not ovar.get().strip():
                ovar.set(str(Path(bvar.get()).with_suffix("")) + suf)

        # --- 입 탭 --- #
        def _lip(self, f):
            self.nb.add(f, text="  ① 입 (립싱크)  ")
            self.l_scd = tk.StringVar(); self.l_b = tk.StringVar(); self.l_o = tk.StringVar()
            self.l_char = tk.StringVar(); self.l_w = tk.StringVar(); self.l_an = tk.BooleanVar()
            self._row(f, 0, "SCD 가사 (.scd)", self.l_scd, types=(("SCD", "*.scd"), ("All", "*.*")))
            self._row(f, 1, "SIFAS 번들 (.unity)", self.l_b,
                      types=(("Unity", "*.unity *.ab *.bundle"), ("All", "*.*")))
            self._row(f, 2, "출력 (.unity)", self.l_o, save=True)
            opt = ttk.Frame(f); opt.grid(row=3, column=0, columnspan=3, sticky="w", pady=6)
            ttk.Label(opt, text="char(빈칸=리드):").grid(row=0, column=0)
            ttk.Entry(opt, textvariable=self.l_char, width=6).grid(row=0, column=1, padx=4)
            ttk.Label(opt, text="weight(빈칸=유지):").grid(row=0, column=2, padx=(12, 0))
            ttk.Entry(opt, textvariable=self.l_w, width=6).grid(row=0, column=3, padx=4)
            ttk.Checkbutton(opt, text="분석만", variable=self.l_an).grid(row=0, column=4, padx=12)
            ttk.Button(f, text="▶ 립싱크 주입", command=self._run_lip).grid(
                row=4, column=0, columnspan=3, sticky="we", pady=8)

        def _run_lip(self):
            scd = self.l_scd.get().strip(); b = self.l_b.get().strip()
            if not scd:
                return messagebox.showerror("오류", "SCD 파일을 선택하세요")
            self._auto(self.l_b, self.l_o, ".lip.unity")
            o = self.l_o.get().strip()
            char = int(self.l_char.get()) if self.l_char.get().strip() else None
            w = float(self.l_w.get()) if self.l_w.get().strip() else None
            an = self.l_an.get()
            if not an and not b:
                return messagebox.showerror("오류", "번들을 선택하거나 '분석만'을 켜세요")

            def task():
                entries, ch, _ = parse_scd(Path(scd), char=char)
                print(f"[scd] char={ch} clips={len(entries)} "
                      f"shapes={dict(Counter(e[2] for e in entries))}")
                if an or not b:
                    for s, d, shp, ph in entries[:12]:
                        print(f"   t={s:7.3f}s {shp} (from '{ph}')")
                    return
                inject_lip(Path(b), entries, Path(o), weight=w)
            self._go(task, "립싱크")

        # --- 표정 탭 --- #
        def _face(self, f):
            self.nb.add(f, text="  ② 표정  ")
            self.f_s = tk.StringVar(); self.f_b = tk.StringVar(); self.f_o = tk.StringVar()
            self.f_blink = tk.BooleanVar(value=True); self.f_dur = tk.StringVar(value="125")
            self._row(f, 0, "표정 스크립트 (.txt, 선택)", self.f_s,
                      types=(("Text", "*.txt"), ("All", "*.*")))
            self._row(f, 1, "SIFAS 번들 (.unity)", self.f_b,
                      types=(("Unity", "*.unity *.ab *.bundle"), ("All", "*.*")))
            self._row(f, 2, "출력 (.unity)", self.f_o, save=True)
            opt = ttk.Frame(f); opt.grid(row=3, column=0, columnspan=3, sticky="w", pady=6)
            ttk.Checkbutton(opt, text="자동 눈깜빡임", variable=self.f_blink).grid(row=0, column=0)
            ttk.Label(opt, text="곡 길이(초):").grid(row=0, column=1, padx=(12, 0))
            ttk.Entry(opt, textvariable=self.f_dur, width=7).grid(row=0, column=2, padx=4)
            ttk.Button(opt, text="표정 이름", command=lambda: messagebox.showinfo(
                "표정 이름", "eye :  " + ", ".join(EYE) + "\n\ngaze:  " + ", ".join(GAZE)
                + "\n\ncheek: " + ", ".join(CHEEK))).grid(row=0, column=3, padx=12)
            ttk.Label(f, foreground="#888",
                      text="형식: <track> <start_s> <dur_s> <name> [weight]   "
                           "예) eye 0 2 Close 1.0 · gaze 1.97 4.3 Camera · cheek 20 0.8 Ppo"
                      ).grid(row=4, column=0, columnspan=3, sticky="w")
            ttk.Button(f, text="▶ 표정 주입", command=self._run_face).grid(
                row=5, column=0, columnspan=3, sticky="we", pady=8)

        def _run_face(self):
            s = self.f_s.get().strip(); b = self.f_b.get().strip()
            if not s and not self.f_blink.get():
                return messagebox.showerror("오류", "스크립트 선택 또는 자동 눈깜빡임을 켜세요")
            if not b:
                return messagebox.showerror("오류", "번들을 선택하세요")
            self._auto(self.f_b, self.f_o, ".face.unity")
            o = self.f_o.get().strip(); dur = float(self.f_dur.get() or "125"); bl = self.f_blink.get()

            def task():
                ents = []
                if s:
                    ents += parse_script(Path(s))
                if bl:
                    ents += auto_blink(duration=dur)
                print(f"[face] {len(ents)} entries by track={dict(Counter(e.track for e in ents))}")
                inject_face(Path(b), ents, Path(o))
            self._go(task, "표정")

        # --- 카메라 탭 (noesis 호출) --- #
        def _cam(self, f):
            self.nb.add(f, text="  ③ 카메라  ")
            self.c_in = tk.StringVar(); self.c_b = tk.StringVar(); self.c_o = tk.StringVar()
            self.c_scale = tk.StringVar(value="1.0"); self.c_z = tk.BooleanVar()
            self.c_yaw = tk.BooleanVar(); self.c_n = tk.StringVar(value=self.noesis or "")
            self._row(f, 0, "카메라 입력 (.bscam/.json)", self.c_in,
                      types=(("Camera", "*.bscam *.json"), ("All", "*.*")))
            self._row(f, 1, "SIFAS 번들 (.unity)", self.c_b,
                      types=(("Unity", "*.unity *.ab *.bundle"), ("All", "*.*")))
            self._row(f, 2, "출력 (.unity)", self.c_o, save=True)
            self._row(f, 3, "noesis tools (.bscam 변환 시에만)", self.c_n)
            opt = ttk.Frame(f); opt.grid(row=4, column=0, columnspan=3, sticky="w", pady=6)
            ttk.Label(opt, text="scale:").grid(row=0, column=0)
            ttk.Entry(opt, textvariable=self.c_scale, width=6).grid(row=0, column=1, padx=4)
            ttk.Checkbutton(opt, text="--z-flip", variable=self.c_z).grid(row=0, column=2, padx=12)
            ttk.Checkbutton(opt, text="--yaw180", variable=self.c_yaw).grid(row=0, column=3, padx=4)
            ttk.Button(f, text="▶ 카메라 주입", command=self._run_cam).grid(
                row=5, column=0, columnspan=3, sticky="we", pady=8)

        def _run_cam(self):
            src = self.c_in.get().strip(); b = self.c_b.get().strip(); nd = self.c_n.get().strip()
            if not src or not b:
                return messagebox.showerror("오류", "카메라 입력과 번들을 선택하세요")
            is_bscam = src.lower().endswith(".bscam")
            if is_bscam and (not nd or not Path(nd, "sifac_camera.py").is_file()):
                return messagebox.showerror("오류",
                    ".bscam 변환에는 noesis-llsifac/tools 폴더가 필요합니다 "
                    "(sifac_camera.py 위치). 또는 .json 을 직접 넣으세요.")
            self._auto(self.c_b, self.c_o, ".cam.unity")
            o = self.c_o.get().strip(); scale = float(self.c_scale.get() or "1.0")
            z = self.c_z.get(); yaw = self.c_yaw.get()

            def task():
                jp = src
                if is_bscam:                       # .bscam → JSON (noesis 추출)
                    if nd and nd not in sys.path:
                        sys.path.insert(0, nd)
                    import importlib
                    sc = importlib.import_module("sifac_camera")
                    jp = str(Path(o).with_suffix("")) + ".camera.json"
                    print(f"[extract] {Path(src).name} -> {Path(jp).name}")
                    sc.convert_file(src, jp)
                inject_camera(Path(jp), Path(b), Path(o), scale=scale, z_flip=z, yaw180=yaw)
            self._go(task, "카메라")

        # --- 실행 엔진 --- #
        def _go(self, task, label):
            if self.busy:
                return messagebox.showwarning("실행 중", "끝날 때까지 기다리세요")
            try:
                import UnityPy  # noqa: F401
            except Exception:
                return messagebox.showerror("UnityPy 필요", "pip install UnityPy 먼저 실행하세요")
            self.busy = True; self.status.config(text=f"{label} 실행 중…")
            self.log.configure(state="normal"); self.log.delete("1.0", "end")
            self.log.configure(state="disabled")

            def worker():
                try:
                    with redirect_stdout(QW(self.q)):
                        task()
                    self.q.put(f"\n✅ {label} 완료\n"); self.q.put(("DONE", label, True))
                except Exception:
                    self.q.put("\n❌ 오류:\n" + traceback.format_exc())
                    self.q.put(("DONE", label, False))
            threading.Thread(target=worker, daemon=True).start()

        def _drain(self):
            try:
                while True:
                    it = self.q.get_nowait()
                    if isinstance(it, tuple) and it and it[0] == "DONE":
                        self.busy = False
                        self.status.config(text=("완료 ✓" if it[2] else "실패 ✗") + f" — {it[1]}")
                        (messagebox.showinfo if it[2] else messagebox.showerror)(
                            "완료" if it[2] else "실패", f"{it[1]} {'완료' if it[2] else '실패 — 로그 확인'}")
                    else:
                        self.log.configure(state="normal"); self.log.insert("end", it)
                        self.log.see("end"); self.log.configure(state="disabled")
            except queue.Empty:
                pass
            self.root.after(80, self._drain)

    root = tk.Tk()
    App(root)
    root.mainloop()


# =========================================================================== #
# CLI
# =========================================================================== #
def main(argv=None):
    ap = argparse.ArgumentParser(description="SIFAS 라이브 멤버 타임라인 주입 (입/표정/GUI)")
    sub = ap.add_subparsers(dest="cmd")

    pl = sub.add_parser("lip", help="SCD 가사 → 입 타임라인")
    pl.add_argument("--scd", required=True)
    pl.add_argument("--bundle"); pl.add_argument("--out")
    pl.add_argument("--char", type=int, default=None)
    pl.add_argument("--weight", type=float, default=None)
    pl.add_argument("--offset", type=float, default=0.0)
    pl.add_argument("--track", default=None)
    pl.add_argument("--analyze-only", action="store_true")
    pl.add_argument("--dry-run", action="store_true")

    pf = sub.add_parser("face", help="표정 스크립트/자동깜빡임 → 눈·시선·볼")
    pf.add_argument("--script"); pf.add_argument("--auto-blink", action="store_true")
    pf.add_argument("--duration", type=float, default=125.0)
    pf.add_argument("--blink-period", type=float, default=3.5)
    pf.add_argument("--bundle"); pf.add_argument("--out")
    pf.add_argument("--list-names", action="store_true")
    pf.add_argument("--dry-run", action="store_true")

    pc = sub.add_parser("cam", help="카메라 JSON → SIFAS Camera1 클립")
    pc.add_argument("--camera", required=True, help="카메라 JSON (noesis sifac_camera.py 출력)")
    pc.add_argument("--bundle", required=True); pc.add_argument("--out")
    pc.add_argument("--scale", type=float, default=1.0)
    pc.add_argument("--z-flip", action="store_true")
    pc.add_argument("--yaw180", action="store_true")

    sub.add_parser("gui", help="GUI 실행 (입·표정·카메라 탭)")

    args = ap.parse_args(argv)

    if args.cmd in (None, "gui"):
        return run_gui()

    if args.cmd == "lip":
        entries, char, cc = parse_scd(Path(args.scd), char=args.char, offset=args.offset)
        print(f"[scd] {Path(args.scd).name}  chars={dict(cc)}  char={char}  "
              f"clips={len(entries)}  shapes={dict(Counter(e[2] for e in entries))}")
        if args.analyze_only or not args.bundle:
            for s, d, shp, ph in entries[:12]:
                print(f"   t={s:7.3f}s {shp} (from '{ph}')")
            return
        out = args.out or (str(Path(args.bundle).with_suffix("")) + ".lip.unity")
        inject_lip(Path(args.bundle), entries, Path(out),
                   weight=args.weight, track_name=args.track, dry_run=args.dry_run)
        return

    if args.cmd == "face":
        if args.list_names:
            print("eye  :", ", ".join(EYE)); print("gaze :", ", ".join(GAZE))
            print("cheek:", ", ".join(CHEEK)); return
        ents = []
        if args.script:
            ents += parse_script(Path(args.script))
        if args.auto_blink:
            ents += auto_blink(duration=args.duration, period=args.blink_period)
        if not ents:
            pf.error("nothing to do: --script and/or --auto-blink")
        print(f"[face] {len(ents)} entries by track={dict(Counter(e.track for e in ents))}")
        if not args.bundle:
            for e in ents[:12]:
                print(f"   {e.track:5} t={e.start:7.3f} dur={e.dur:.3f} {e.name} w={e.weight}")
            return
        out = args.out or (str(Path(args.bundle).with_suffix("")) + ".face.unity")
        inject_face(Path(args.bundle), ents, Path(out), dry_run=args.dry_run)
        return

    if args.cmd == "cam":
        out = args.out or (str(Path(args.bundle).with_suffix("")) + ".cam.unity")
        inject_camera(Path(args.camera), Path(args.bundle), Path(out),
                      scale=args.scale, z_flip=args.z_flip, yaw180=args.yaw180)
        return


if __name__ == "__main__":
    main()
