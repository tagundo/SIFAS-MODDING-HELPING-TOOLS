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
    gui   네 탭(입·표정·카메라·따라가기) GUI 실행  (.bmarc 읽을 때만 noesis 파서 sifac_bmarc 사용)

  # 입: SIFAC 음소 코드 [들어오는모음][자음][목표모음] → 마지막 모음이 입모양
  #     (oto→O, usu→U, ete→E). 화이트리스트 없이 미지 코드 0%.
  # 입모양 테이블(실번들 확인): A=1 I=2 U=3 E=4 O=5 N=6  (E2=13, Laugh=8)
  # 표정 테이블(실번들 확인):
  #   Eye : Close=1 Closish=2 Open=3 WideOpen=4 Close_Smile=5 WinkR=12 WinkL=13
  #         Trouble=14 Sad=15 Angry=16 Shy=17 Missing=18 Tightly=19 EyeGreatSmile=20
  #         EyeDepend=21 EyeSmug=22 EyeHalf=23 EyeKobi=24 EyeAngryClose=25  (+weight)
  #   Gaze: Member1..12=1..12 Camera=21 Audience=22 Up=31 Down=32 Left=33 Right=34
  #         LeftUp=35 RightUp=36 SplitScreenCamera1..4=37..40   (+weightForDirection)
  #   Cheek: Ppo, Akarame  (+intensity)  ← cheekType, NOT weight

예:
    python3 sifas_timeline_inject.py lip  --scd lyrics.scd --bundle live.unity --out o.unity --weight 1.0
    # 곡 길이 맞춤(자르기): 앞 8초 자르기 / 앞뒤 자르기(곡 길이 106초)
    python3 sifas_timeline_inject.py lip  --scd lyrics.scd --analyze-only --trim-start 8
    python3 sifas_timeline_inject.py lip  --scd lyrics.scd --bundle live.unity --trim-start 8 --length 106
    python3 sifas_timeline_inject.py face --script faces.txt --auto-blink --bundle live.unity --out o.unity
    python3 sifas_timeline_inject.py face --list-names
    # 따라가기 카메라(front/rear): 동작 .bmarc(또는 위치 .json) → 첫 카메라 (위치추출 내장)
    python3 sifas_timeline_inject.py cam-follow --positions mot.bmarc --noesis <noesis/tools> --bundle live.unity \
            --view front --front-dist 4 --threshold 1.0 --front-yaw 0
    # 곡 길이 맞춤(립싱크와 동일): 앞 8초 자르고 곡 길이 106초로 고정
    python3 sifas_timeline_inject.py cam-follow --positions mot.bmarc --bundle live.unity --start 8 --length 106
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


def trim_entries(entries, start=0.0, end=None, rebase=True, min_dur=0.04):
    """곡 길이에 맞춰 입 타임라인을 자른다.

    SIFAC 립싱크 길이가 SIFAS 곡 길이와 다를 때(앞 인트로가 길거나 뒤가 남을 때) 사용.
    `start`/`end` 는 (offset 적용 후) 표시되는 원본 시간(초). 유지 구간 [start, end] 밖의
    클립은 버리고, 경계에 걸친 클립은 잘라낸다.

      * 앞 자르기      : start>0            (그 지점 이전을 버림)
      * 뒤 자르기      : end 지정           (그 지점 이후를 버림)
      * 앞뒤 자르기    : start>0 과 end 함께
      * rebase=True(기본): start 가 새 0 이 되도록 왼쪽으로 당김(잘린 인트로만큼 앞으로).
        rebase=False     : 절대 시간 유지(앞만 비우고 당기지 않음).
    """
    out = []
    for s, d, shp, ph in entries:
        e0, e1 = s, s + d
        if e1 <= start:                       # 완전히 앞 → 버림
            continue
        if end is not None and e0 >= end:     # 완전히 뒤 → 버림
            continue
        ns = max(e0, start)
        ne = e1 if end is None else min(e1, end)
        nd = ne - ns
        if nd < min_dur:
            continue
        if rebase:
            ns -= start
        out.append((ns, nd, shp, ph))
    out.sort(key=lambda e: e[0])
    return out


def format_lip_timeline(entries, head=None):
    """입 클립 목록을 사람이 읽기 좋은 여러 줄 문자열로(번호·시작→끝·길이·입모양·원본 코드)."""
    shown = entries[:head] if head else entries
    cap = f" (앞 {head}개만)" if head and len(entries) > head else ""
    lines = [f"[timeline] {len(entries)} mouth clips{cap}:"]
    for i, (s, d, shp, ph) in enumerate(shown, 1):
        lines.append(f"   #{i:3}  t={s:8.3f}→{s + d:8.3f}  ({d:5.2f}s)  {shp:5} from '{ph}'")
    if head and len(entries) > head:
        lines.append(f"   … +{len(entries) - head} more")
    return "\n".join(lines)


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
        if len(entries) > len(clips):
            print(f"[lip] WARNING: {len(entries) - len(clips)} of {len(entries)} entries "
                  f"DROPPED on '{t.get('m_Name')}' — it has only {len(clips)} clips and this "
                  f"tool overwrites existing clips (it cannot add new ones), so the tail of the "
                  f"song will have NO lip-sync. Use fewer/merged entries or a track with more clips.")
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
# Values verified against the SIFAS 3.12.0 client decompile (MemberEyeClip /
# MemberGazeClip / MemberCheekClip AnimationIndex enums).
# NOTE: eye 6..11 are directional GAZE poses (not in MemberEyeClip's enum), so they
# are intentionally absent here — set them through the gaze track instead.
EYE = {"Close": 1, "Closish": 2, "Open": 3, "WideOpen": 4, "Close_Smile": 5,
       "WinkR": 12, "WinkL": 13, "Trouble": 14, "Sad": 15, "Angry": 16, "Shy": 17,
       "Missing": 18, "Tightly": 19, "EyeGreatSmile": 20, "EyeDepend": 21,
       "EyeSmug": 22, "EyeHalf": 23, "EyeKobi": 24, "EyeAngryClose": 25,
       "RinNyaa": 101, "RinaMaskOdoroki": 102, "EyeBlinkNavi": 900}
GAZE = {"Member1": 1, "Member2": 2, "Member3": 3, "Member4": 4, "Member5": 5,
        "Member6": 6, "Member7": 7, "Member8": 8, "Member9": 9, "Member10": 10,
        "Member11": 11, "Member12": 12, "Camera": 21, "Audience": 22,
        "Up": 31, "Down": 32, "Left": 33, "Right": 34, "LeftUp": 35, "RightUp": 36,
        "SplitScreenCamera1": 37, "SplitScreenCamera2": 38,
        "SplitScreenCamera3": 39, "SplitScreenCamera4": 40}
# Cheek clips carry `cheekType` (Ppo=0/Akarame=1) + `intensity` — there is NO
# `weight` field on MemberCheekClip (writing 'weight' silently does nothing).
CHEEK = {"Ppo": 0, "Akarame": 1}

TRACK_CLASS = {
    "eye":   ("MemberEyeTrack",   "index", EYE),
    "gaze":  ("MemberGazeTrack",  "target", GAZE),
    "cheek": ("MemberCheekTrack", "cheekType", CHEEK),
}
WEIGHT_FIELD = {"eye": "weight", "gaze": "weightForDirection", "cheek": "intensity"}


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
        # one track per on-stage member — write ALL of them, not just the first, so
        # every member gets the eye/gaze/cheek (esp. the ambient --auto-blink). Writing
        # only track_objs[0] left 8 of 9 members un-animated.
        wfield = WEIGHT_FIELD[kind]
        track_data = [(o, o.read_typetree()) for o in track_objs]
        max_clips = max((len(t.get("m_Clips", [])) for _, t in track_data), default=0)
        if len(ents) > max_clips:
            print(f"[face] WARNING: {len(ents) - max_clips} of {len(ents)} {kind} entries "
                  f"DROPPED — '{cls}' tracks have at most {max_clips} clips and this tool "
                  f"overwrites existing clips (it cannot add new ones), so late {kind} entries "
                  f"are lost.")
        for o, t in track_data:
            clips = t.get("m_Clips", [])
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
            print(f"[face] {cls}: wrote up to {len(ents)} entries across "
                  f"{len(track_objs)} track(s) ({kind})")

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


def build_sample_array(samples, scale=1.0, z_flip=False, yaw180=False, order=None):
    """samples → DenseClip flat float array × N.

    `order` 는 클립의 genericBindings 순서를 따른 ['pos','euler','fov'] 리스트.
    클립마다 바인딩 순서가 다를 수 있어(예: pos,FOV,euler) 반드시 실제 순서대로 써야
    FOV/회전이 안 뒤섞인다. 기본값은 가장 흔한 pos,euler,fov.
    """
    if order is None:
        order = ["pos", "euler", "fov"]
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
        for b in order:
            if b == "pos":
                arr.extend([px, py, pz])
            elif b == "euler":
                arr.extend([ex, ey, ez])
            else:                       # fov (단일 커브)
                arr.append(float(fov))
    return arr


# Unity transform-binding attribute: 1=position, 2=rotation, 3=scale, 4=euler.
# 그 외(스크립트 float 해시)는 FOV.
def _binding_order(generic_bindings):
    """genericBindings → ['pos'|'euler'|'fov', ...] (클립의 실제 커브 순서)."""
    out = []
    for b in generic_bindings:
        at = b.get("attribute")
        out.append("pos" if at == 1 else "euler" if at == 4 else "fov")
    return out


def inject_camera(camera_json: Path, bundle_in: Path, bundle_out: Path,
                  scale=1.0, z_flip=False, yaw180=False, verbose=True):
    import UnityPy
    track = json.loads(Path(camera_json).read_text(encoding="utf-8"))
    samples = resample_60(track.get("frames", []))
    n = len(samples)
    if n == 0:
        raise ValueError("camera json has no frames")
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

    # 이 클립의 실제 바인딩 순서대로 써야 FOV/회전이 안 뒤섞인다(클립마다 다름).
    order = _binding_order(ct["m_ClipBindingConstant"]["genericBindings"])
    n_curves = sum(3 if b in ("pos", "euler") else 1 for b in order)
    sample_array = build_sample_array(samples, scale=scale, z_flip=z_flip,
                                      yaw180=yaw180, order=order)

    clip = ct["m_MuscleClip"]["m_Clip"]["data"]
    clip["m_StreamedClip"]["data"] = []; clip["m_StreamedClip"]["curveCount"] = 0
    dense = clip["m_DenseClip"]
    dense["m_FrameCount"] = n; dense["m_CurveCount"] = n_curves
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


# --------------------------------------------------------------------------- #
# 따라가기 카메라 생성 (front/rear view) — 캐릭터 위치를 따라가며 앞/뒤에서 촬영
# --------------------------------------------------------------------------- #
# 입력: 캐릭터 위치 트랙 JSON {"fps":60,"frames":[{"t":..,"pos":[x,y,z]},...]}
#       (.bmarc 입력 시 extract_motion_path 가 동작 모션 루트에서 위치 추출)
# 동작: 무대 정면(고정 방향) 기준으로 캐릭터의 앞(front) / 뒤(rear)에 카메라를 두고
#       항상 캐릭터를 바라봄. 캐릭터가 dead-zone(임계 m) 이상 움직일 때만 따라감.
# 출력: inject_camera 가 먹는 카메라 JSON(frames: pos/rot(quat)/fov).

def _look_rotation(fwd, up=(0.0, 1.0, 0.0)):
    """Unity 식 LookRotation: +Z가 fwd, +Y가 up 인 쿼터니언(x,y,z,w)."""
    def _n(v):
        m = math.sqrt(sum(c * c for c in v)) or 1.0
        return [v[0] / m, v[1] / m, v[2] / m]

    def _cross(a, b):
        return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2],
                a[0] * b[1] - a[1] * b[0]]
    f = _n(fwd)
    r = _n(_cross(up, f))
    u = _cross(f, r)
    m00, m01, m02 = r[0], u[0], f[0]
    m10, m11, m12 = r[1], u[1], f[1]
    m20, m21, m22 = r[2], u[2], f[2]
    tr = m00 + m11 + m22
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2
        w = 0.25 * s; x = (m21 - m12) / s; y = (m02 - m20) / s; z = (m10 - m01) / s
    elif m00 > m11 and m00 > m22:
        s = math.sqrt(1.0 + m00 - m11 - m22) * 2
        w = (m21 - m12) / s; x = 0.25 * s; y = (m01 + m10) / s; z = (m02 + m20) / s
    elif m11 > m22:
        s = math.sqrt(1.0 + m11 - m00 - m22) * 2
        w = (m02 - m20) / s; x = (m01 + m10) / s; y = 0.25 * s; z = (m12 + m21) / s
    else:
        s = math.sqrt(1.0 + m22 - m00 - m11) * 2
        w = (m10 - m01) / s; x = (m02 + m20) / s; y = (m12 + m21) / s; z = 0.25 * s
    n = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    return [x / n, y / n, z / n, w / n]


def follow_targets(positions, threshold=1.0, smooth=0.0):
    """위치 시퀀스([(x,y,z)..]) → dead-zone 따라가기 타깃 시퀀스.

    수평(x,z) 이동이 `threshold` m 를 넘을 때만 타깃이 끌려감(그 이하 움직임은 무시 →
    화면이 안 흔들림). `smooth`(0~1)는 dead-zone 결과에 EMA 평활을 추가(0=없음).
    """
    if not positions:
        return []
    out = []
    ax, ay, az = positions[0]          # dead-zone anchor
    sx, sy, sz = positions[0]          # smoothed output
    a = max(0.0, min(0.99, smooth))
    for px, py, pz in positions:
        dx, dz = px - ax, pz - az
        d = math.hypot(dx, dz)
        if d > threshold:              # dead-zone 밖 → 임계 거리만큼만 끌려감
            f = (d - threshold) / d
            ax += dx * f; az += dz * f
        ay = py                        # 수직은 그대로 추종(점프 등)
        # 선택적 EMA 평활 (급격한 스냅 완화)
        sx += (ax - sx) * (1.0 - a)
        sy += (ay - sy) * (1.0 - a)
        sz += (az - sz) * (1.0 - a)
        out.append((sx, sy, sz))
    return out


def generate_follow_camera(positions, *, view="front", front_dist=4.0, rear_dist=4.0,
                           height=1.2, lookat_height=1.1, fov=32.0, threshold=1.0,
                           front_yaw=0.0, smooth=0.0, fps=60.0,
                           start=0.0, end=None, length=None, rebase=True):
    """캐릭터 위치 트랙 → front/rear 따라가기 카메라 JSON(dict).

    * positions: [{"t":sec,"pos":[x,y,z]}, ...] (시간순)
    * view: "front"(관객 쪽에서 얼굴) | "rear"(뒤에서 등)
    * front_yaw: 무대 정면 방향(도). 0=+Z. 카메라가 반대편이면 180 으로 뒤집기.
    * threshold: 이 거리(m) 이상 움직여야 따라감(dead-zone).
    * 곡 길이 맞춤(자르기):
        start  : 앞 자르기 — 이 시각(초) 이전을 버림
        end    : 뒤 자르기 — 이 시각(초) 이후를 버림
        length : 곡 길이(초)에 맞춰 유지 구간 고정 (= end 를 start+length 로)
        rebase : True(기본) 면 start 가 새 0 이 되도록 당김; False 면 절대시간 유지
    """
    if not positions:
        raise ValueError("position track is empty")
    if length is not None:
        t_end = start + length
    else:
        t_end = positions[-1]["t"] if end is None else end
    # fps 그리드로 위치 보간
    grid = []
    j = 0
    n = int(round((t_end - start) * fps)) + 1
    for i in range(max(1, n)):
        t = start + i / fps
        while j + 1 < len(positions) and positions[j + 1]["t"] < t:
            j += 1
        p0 = positions[j]; p1 = positions[min(j + 1, len(positions) - 1)]
        span = (p1["t"] - p0["t"]) or 1.0
        a = max(0.0, min(1.0, (t - p0["t"]) / span))
        pos = [p0["pos"][k] + (p1["pos"][k] - p0["pos"][k]) * a for k in range(3)]
        grid.append((t, pos))
    targets = follow_targets([p for _t, p in grid], threshold=threshold, smooth=smooth)
    yaw = math.radians(front_yaw)
    fdir = (math.sin(yaw), 0.0, math.cos(yaw))     # 무대 정면(수평)
    sign = 1.0 if view == "front" else -1.0
    dist = front_dist if view == "front" else rear_dist
    frames = []
    for (t, _p), (tx, ty, tz) in zip(grid, targets):
        cam = [tx + fdir[0] * sign * dist, ty + height, tz + fdir[2] * sign * dist]
        look = [tx, ty + lookat_height, tz]
        rot = _look_rotation([look[0] - cam[0], look[1] - cam[1], look[2] - cam[2]])
        frames.append({"t": round((t - start) if rebase else t, 5),
                       "pos": [round(c, 5) for c in cam],
                       "rot": [round(c, 6) for c in rot], "fov": float(fov)})
    return {"fps": fps, "view": view, "frames": frames}


# --- 동작 모션(.bmarc) → 캐릭터 위치 트랙 (SIFAC 파서 sifac_bmarc 만 빌려 씀) ----- #
# 위치 추출 로직은 여기(이 도구) 안에 통합. .bmarc 를 읽을 때만 noesis 의 *파서*
# sifac_bmarc 를 지연 import 한다(SIFAC 포맷이라 그 파서가 필요. noesis 가 실제로
# 쓰는 진짜 파서이고, 별도 글루 파일은 두지 않는다).
_ROOT_HINTS = ("trans", "root", "footsteps", "shoe_sole", "hips", "center", "reference")


def _motion_span(track):
    tr = track.translation
    if len(tr) < 2:
        return 0.0
    xs = [p[1].x for p in tr]; ys = [p[1].y for p in tr]; zs = [p[1].z for p in tr]
    return max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))


def _pick_root_bone(anim, name=None):
    """위치를 대표할 본: name 지정 우선, 없으면 이동량 큰 루트 후보(없으면 Hips류)."""
    tracks = anim.tracks
    names = [t.bone_name for t in tracks]
    if name:
        if name not in names:
            raise ValueError("bone %r not found; bones=%s" % (name, names[:40]))
        return tracks[names.index(name)]
    cands = sorted((t for t in tracks
                    if any(h in t.bone_name.lower() for h in _ROOT_HINTS)),
                   key=_motion_span, reverse=True)
    if cands and _motion_span(cands[0]) > 1e-4:
        return cands[0]
    for pref in ("Hips", "Kotori_trans", "Kotori_root"):
        if pref in names:
            return tracks[names.index(pref)]
    return cands[0] if cands else tracks[0]


def extract_motion_path(motion, bone=None, fps=60.0, scale=1.0, z_flip=False,
                        tools_dir=None):
    """SIFAC 동작 bmarc → 위치 트랙 dict {fps,bone,frames:[{t,pos[xyz]}]}.

    `tools_dir` = noesis-llsifac/tools (sifac_bmarc 파서 위치). 제자리 춤이면 트랙이
    거의 고정값이라 카메라가 안정적인 front/rear 샷이 된다.
    """
    import importlib
    if tools_dir and str(tools_dir) not in sys.path:
        sys.path.insert(0, str(tools_dir))
    B = importlib.import_module("sifac_bmarc")          # noesis 의 SIFAC 파서
    m = B.parse_bmarc(Path(motion).read_bytes(), Path(motion).stem)
    if not m.animations:
        raise ValueError("no animation in %s" % motion)
    anim = m.animations[0]
    bt = _pick_root_bone(anim, bone)
    keys = bt.translation or [(0, type("V", (), {"x": 0, "y": 0, "z": 0})())]
    src_fps = anim.fps or 60.0
    end_frame = anim.end_frame or keys[-1][0]
    kf = [(k[0] / src_fps, k[1].x, k[1].y, k[1].z) for k in keys]
    frames, j = [], 0
    n = int(round((end_frame / src_fps) * fps)) + 1
    for i in range(max(1, n)):
        t = i / fps
        while j + 1 < len(kf) and kf[j + 1][0] < t:
            j += 1
        a = kf[j]; b = kf[min(j + 1, len(kf) - 1)]
        span = (b[0] - a[0]) or 1.0
        u = max(0.0, min(1.0, (t - a[0]) / span))
        x = (a[1] + (b[1] - a[1]) * u) * scale
        y = (a[2] + (b[2] - a[2]) * u) * scale
        z = (a[3] + (b[3] - a[3]) * u) * scale
        if z_flip:
            z = -z
        frames.append({"t": round(t, 5), "pos": [round(x, 5), round(y, 5), round(z, 5)]})
    return {"fps": fps, "bone": bt.bone_name, "frames": frames}


def inject_follow_camera(positions_json: Path, bundle_in: Path, bundle_out: Path, *,
                         view="front", front_dist=4.0, rear_dist=4.0, height=1.2,
                         lookat_height=1.1, fov=32.0, threshold=1.0, front_yaw=0.0,
                         smooth=0.0, start=0.0, end=None, length=None, rebase=True,
                         scale=1.0, z_flip=False, yaw180=False, out_json=None,
                         verbose=True):
    """위치 JSON → 따라가기 카메라 생성 → 첫 카메라 클립에 주입(inject_camera 재사용)."""
    data = json.loads(Path(positions_json).read_text(encoding="utf-8"))
    pos = data.get("frames", data) if isinstance(data, dict) else data
    cam = generate_follow_camera(pos, view=view, front_dist=front_dist,
                                 rear_dist=rear_dist, height=height,
                                 lookat_height=lookat_height, fov=fov,
                                 threshold=threshold, front_yaw=front_yaw,
                                 smooth=smooth, end=end, start=start,
                                 length=length, rebase=rebase)
    tmp = Path(out_json) if out_json else Path(str(bundle_out) + ".followcam.json")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(json.dumps(cam), encoding="utf-8")
    if verbose:
        print(f"[follow] view={view} dist={front_dist if view=='front' else rear_dist} "
              f"threshold={threshold}m frames={len(cam['frames'])} -> {tmp.name}")
    inject_camera(tmp, bundle_in, bundle_out, scale=scale, z_flip=z_flip,
                  yaw180=yaw180, verbose=verbose)


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
            root.title("SIFAS 라이브 주입 (입 · 표정 · 카메라 · 따라가기)")
            root.geometry("760x680")
            self.q = queue.Queue(); self.busy = False
            self.noesis = _find_noesis_tools()
            self.nb = ttk.Notebook(root)
            self.nb.pack(fill="both", expand=True, padx=8, pady=(8, 0))
            self._lip(ttk.Frame(self.nb, padding=10))
            self._face(ttk.Frame(self.nb, padding=10))
            self._cam(ttk.Frame(self.nb, padding=10))
            self._camfollow(ttk.Frame(self.nb, padding=10))
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
            self.l_off = tk.StringVar(); self.l_ts = tk.StringVar(); self.l_te = tk.StringVar()
            self.l_len = tk.StringVar(); self.l_norebase = tk.BooleanVar()
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
            # 곡 길이 맞춤(자르기) 옵션
            trm = ttk.LabelFrame(f, text="곡 길이 맞춤 (자르기)")
            trm.grid(row=4, column=0, columnspan=3, sticky="we", pady=(0, 6))
            ttk.Label(trm, text="offset(초):").grid(row=0, column=0, padx=(6, 0))
            ttk.Entry(trm, textvariable=self.l_off, width=7).grid(row=0, column=1, padx=4)
            ttk.Label(trm, text="앞 자르기 trim-start:").grid(row=0, column=2)
            ttk.Entry(trm, textvariable=self.l_ts, width=7).grid(row=0, column=3, padx=4)
            ttk.Label(trm, text="뒤 자르기 trim-end:").grid(row=0, column=4)
            ttk.Entry(trm, textvariable=self.l_te, width=7).grid(row=0, column=5, padx=4)
            ttk.Label(trm, text="또는 곡 길이 length:").grid(row=1, column=2, pady=(2, 4))
            ttk.Entry(trm, textvariable=self.l_len, width=7).grid(row=1, column=3, pady=(2, 4))
            ttk.Checkbutton(trm, text="당기지 않음(절대시간)",
                            variable=self.l_norebase).grid(row=1, column=4, columnspan=2, sticky="w")
            ttk.Button(f, text="▶ 립싱크 주입", command=self._run_lip).grid(
                row=5, column=0, columnspan=3, sticky="we", pady=8)

        def _run_lip(self):
            scd = self.l_scd.get().strip(); b = self.l_b.get().strip()
            if not scd:
                return messagebox.showerror("오류", "SCD 파일을 선택하세요")
            self._auto(self.l_b, self.l_o, ".lip.unity")
            o = self.l_o.get().strip()
            char = int(self.l_char.get()) if self.l_char.get().strip() else None
            w = float(self.l_w.get()) if self.l_w.get().strip() else None
            an = self.l_an.get()

            def _f(var, d=None):
                s = var.get().strip()
                return float(s) if s else d
            off = _f(self.l_off, 0.0); ts = _f(self.l_ts, 0.0)
            te = _f(self.l_te, None); ln = _f(self.l_len, None)
            norebase = self.l_norebase.get()
            if not an and not b:
                return messagebox.showerror("오류", "번들을 선택하거나 '분석만'을 켜세요")

            def task():
                entries, ch, _ = parse_scd(Path(scd), char=char, offset=off)
                print(f"[scd] char={ch} clips={len(entries)} "
                      f"shapes={dict(Counter(e[2] for e in entries))}")
                trim_end = (ts + ln) if ln is not None else te
                if ts or trim_end is not None:
                    before = len(entries)
                    entries[:] = trim_entries(entries, start=ts, end=trim_end,
                                              rebase=not norebase)
                    print(f"[trim] start={ts} end={trim_end} rebase={not norebase}: "
                          f"{before} → {len(entries)} clips")
                print(format_lip_timeline(entries))      # (자른 뒤) 전체 타임라인
                if an or not b:
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

        # --- 따라가기 카메라 탭 (front/rear) --- #
        def _camfollow(self, f):
            self.nb.add(f, text="  ④ 따라가기 카메라  ")
            self.cf_in = tk.StringVar(); self.cf_b = tk.StringVar(); self.cf_o = tk.StringVar()
            self.cf_n = tk.StringVar(value=self.noesis or "")
            self.cf_view = tk.StringVar(value="front")
            self.cf_fd = tk.StringVar(value="4.0"); self.cf_rd = tk.StringVar(value="4.0")
            self.cf_h = tk.StringVar(value="1.2"); self.cf_lh = tk.StringVar(value="1.1")
            self.cf_fov = tk.StringVar(value="32"); self.cf_th = tk.StringVar(value="1.0")
            self.cf_fy = tk.StringVar(value="0"); self.cf_sm = tk.StringVar(value="0")
            self.cf_st = tk.StringVar(); self.cf_en = tk.StringVar()
            self.cf_len = tk.StringVar(); self.cf_norebase = tk.BooleanVar()
            self.cf_scale = tk.StringVar(value="1.0")
            self.cf_z = tk.BooleanVar(); self.cf_yaw = tk.BooleanVar()
            self._row(f, 0, "위치/모션 입력 (.bmarc/.json)", self.cf_in,
                      types=(("Motion/Pos", "*.bmarc *.json"), ("All", "*.*")))
            self._row(f, 1, "SIFAS 번들 (.unity)", self.cf_b,
                      types=(("Unity", "*.unity *.ab *.bundle"), ("All", "*.*")))
            self._row(f, 2, "출력 (.unity)", self.cf_o, save=True)
            self._row(f, 3, "noesis tools (.bmarc 추출 시에만)", self.cf_n)
            p1 = ttk.Frame(f); p1.grid(row=4, column=0, columnspan=3, sticky="w", pady=4)
            ttk.Label(p1, text="view:").grid(row=0, column=0)
            ttk.Combobox(p1, textvariable=self.cf_view, values=["front", "rear"],
                         state="readonly", width=7).grid(row=0, column=1, padx=4)
            ttk.Label(p1, text="앞거리:").grid(row=0, column=2)
            ttk.Entry(p1, textvariable=self.cf_fd, width=5).grid(row=0, column=3, padx=2)
            ttk.Label(p1, text="뒤거리:").grid(row=0, column=4)
            ttk.Entry(p1, textvariable=self.cf_rd, width=5).grid(row=0, column=5, padx=2)
            ttk.Label(p1, text="fov:").grid(row=0, column=6)
            ttk.Entry(p1, textvariable=self.cf_fov, width=5).grid(row=0, column=7, padx=2)
            p2 = ttk.Frame(f); p2.grid(row=5, column=0, columnspan=3, sticky="w", pady=4)
            ttk.Label(p2, text="높이:").grid(row=0, column=0)
            ttk.Entry(p2, textvariable=self.cf_h, width=5).grid(row=0, column=1, padx=2)
            ttk.Label(p2, text="보는높이:").grid(row=0, column=2)
            ttk.Entry(p2, textvariable=self.cf_lh, width=5).grid(row=0, column=3, padx=2)
            ttk.Label(p2, text="threshold(m):").grid(row=0, column=4)
            ttk.Entry(p2, textvariable=self.cf_th, width=5).grid(row=0, column=5, padx=2)
            ttk.Label(p2, text="front-yaw:").grid(row=0, column=6)
            ttk.Entry(p2, textvariable=self.cf_fy, width=5).grid(row=0, column=7, padx=2)
            p3 = ttk.Frame(f); p3.grid(row=6, column=0, columnspan=3, sticky="w", pady=4)
            ttk.Label(p3, text="smooth:").grid(row=0, column=0)
            ttk.Entry(p3, textvariable=self.cf_sm, width=5).grid(row=0, column=1, padx=2)
            ttk.Label(p3, text="scale:").grid(row=0, column=2)
            ttk.Entry(p3, textvariable=self.cf_scale, width=5).grid(row=0, column=3, padx=2)
            ttk.Checkbutton(p3, text="z-flip", variable=self.cf_z).grid(row=0, column=4, padx=6)
            ttk.Checkbutton(p3, text="yaw180", variable=self.cf_yaw).grid(row=0, column=5)
            # 곡 길이 맞춤(자르기) — 립싱크 탭과 동일
            trm = ttk.LabelFrame(f, text="곡 길이 맞춤 (자르기)")
            trm.grid(row=7, column=0, columnspan=3, sticky="we", pady=(0, 6))
            ttk.Label(trm, text="앞 자르기 trim-start:").grid(row=0, column=0, padx=(6, 0))
            ttk.Entry(trm, textvariable=self.cf_st, width=7).grid(row=0, column=1, padx=4)
            ttk.Label(trm, text="뒤 자르기 trim-end:").grid(row=0, column=2)
            ttk.Entry(trm, textvariable=self.cf_en, width=7).grid(row=0, column=3, padx=4)
            ttk.Label(trm, text="또는 곡 길이 length:").grid(row=1, column=0, padx=(6, 0), pady=(2, 4))
            ttk.Entry(trm, textvariable=self.cf_len, width=7).grid(row=1, column=1, pady=(2, 4))
            ttk.Checkbutton(trm, text="당기지 않음(절대시간)",
                            variable=self.cf_norebase).grid(row=1, column=2, columnspan=2, sticky="w")
            ttk.Label(f, text="앞/뒤는 무대 정면(front-yaw) 기준. 카메라가 반대편이면 "
                             "front-yaw=180. 캐릭터가 threshold(m) 이상 움직일 때만 따라감.",
                      foreground="#888").grid(row=8, column=0, columnspan=3, sticky="w", pady=(2, 0))
            ttk.Button(f, text="▶ 따라가기 카메라 주입", command=self._run_camfollow).grid(
                row=9, column=0, columnspan=3, sticky="we", pady=8)

        def _run_camfollow(self):
            src = self.cf_in.get().strip(); b = self.cf_b.get().strip()
            nd = self.cf_n.get().strip()
            if not src or not b:
                return messagebox.showerror("오류", "위치/모션 입력과 번들을 선택하세요")
            is_bmarc = src.lower().endswith(".bmarc")
            if is_bmarc and (not nd or not Path(nd, "sifac_bmarc.py").is_file()):
                return messagebox.showerror("오류",
                    ".bmarc 읽기에는 SIFAC 파서가 필요합니다 — noesis-llsifac/tools 폴더 "
                    "(sifac_bmarc.py) 경로를 넣으세요. 또는 위치 .json 을 직접 넣으세요.")
            self._auto(self.cf_b, self.cf_o, ".follow.unity")
            o = self.cf_o.get().strip()

            def _f(var, d=None):
                s = var.get().strip()
                return float(s) if s else d
            params = dict(
                view=self.cf_view.get() or "front",
                front_dist=_f(self.cf_fd, 4.0), rear_dist=_f(self.cf_rd, 4.0),
                height=_f(self.cf_h, 1.2), lookat_height=_f(self.cf_lh, 1.1),
                fov=_f(self.cf_fov, 32.0), threshold=_f(self.cf_th, 1.0),
                front_yaw=_f(self.cf_fy, 0.0), smooth=_f(self.cf_sm, 0.0),
                start=_f(self.cf_st, 0.0), end=_f(self.cf_en, None),
                length=_f(self.cf_len, None), rebase=not self.cf_norebase.get(),
                scale=_f(self.cf_scale, 1.0), z_flip=self.cf_z.get(), yaw180=self.cf_yaw.get())

            def task():
                posjson = src
                if is_bmarc:                       # .bmarc → 위치 JSON (이 도구가 추출)
                    track = extract_motion_path(src, tools_dir=nd or None)
                    posjson = str(Path(o).with_suffix("")) + ".path.json"
                    Path(posjson).write_text(json.dumps(track), encoding="utf-8")
                    print(f"[path] bone={track['bone']} frames={len(track['frames'])} "
                          f"-> {Path(posjson).name}")
                inject_follow_camera(Path(posjson), Path(b), Path(o), **params)
            self._go(task, "따라가기 카메라")

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
    pl.add_argument("--trim-start", type=float, default=0.0,
                    help="이 시각(초) 이전을 자르고 그 지점을 새 0으로 당김 (앞 자르기)")
    pl.add_argument("--trim-end", type=float, default=None,
                    help="이 시각(초) 이후를 자름 (뒤 자르기)")
    pl.add_argument("--length", type=float, default=None,
                    help="곡 길이(초)에 맞춰 유지 구간 길이 고정 (= trim-end 를 trim-start+length 로)")
    pl.add_argument("--no-rebase", action="store_true",
                    help="앞을 잘라도 시간을 0으로 당기지 않음(절대 시간 유지)")
    pl.add_argument("--head", type=int, default=None, help="타임라인 출력 줄 수 제한(기본=전체)")
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

    pcf = sub.add_parser("cam-follow",
                         help="캐릭터 위치 따라가기 front/rear 카메라 생성→첫 카메라 주입")
    pcf.add_argument("--positions", required=True,
                     help="위치 트랙 .json 또는 동작 .bmarc (bmarc 면 자동으로 위치 추출)")
    pcf.add_argument("--bone", default=None, help="(.bmarc) 위치를 따올 본(기본=자동)")
    pcf.add_argument("--noesis", default=None,
                     help="(.bmarc) sifac_bmarc.py 가 있는 noesis-llsifac/tools 경로")
    pcf.add_argument("--bundle"); pcf.add_argument("--out")
    pcf.add_argument("--view", choices=["front", "rear"], default="front")
    pcf.add_argument("--front-dist", type=float, default=4.0, help="앞 거리(m)")
    pcf.add_argument("--rear-dist", type=float, default=4.0, help="뒤 거리(m)")
    pcf.add_argument("--height", type=float, default=1.2, help="카메라 높이(m)")
    pcf.add_argument("--lookat-height", type=float, default=1.1, help="바라보는 높이(m)")
    pcf.add_argument("--fov", type=float, default=32.0)
    pcf.add_argument("--threshold", type=float, default=1.0,
                     help="이 거리(m) 이상 움직일 때만 따라감(dead-zone)")
    pcf.add_argument("--front-yaw", type=float, default=0.0,
                     help="무대 정면 방향(도). 카메라가 반대편이면 180")
    pcf.add_argument("--smooth", type=float, default=0.0, help="0~1 추가 평활")
    # 곡 길이 맞춤(자르기) — 립싱크와 동일
    pcf.add_argument("--start", type=float, default=0.0,
                     help="앞 자르기: 이 시각(초) 이전을 버리고 0으로 당김")
    pcf.add_argument("--end", type=float, default=None, help="뒤 자르기: 이 시각(초) 이후 버림")
    pcf.add_argument("--length", type=float, default=None,
                     help="곡 길이(초)에 맞춰 유지 구간 고정 (= end 를 start+length 로)")
    pcf.add_argument("--no-rebase", action="store_true",
                     help="앞을 잘라도 시간을 0으로 당기지 않음(절대시간 유지)")
    pcf.add_argument("--scale", type=float, default=1.0)
    pcf.add_argument("--z-flip", action="store_true")
    pcf.add_argument("--yaw180", action="store_true")
    pcf.add_argument("--emit-json", help="생성한 카메라 JSON만 저장(번들 없이)")

    sub.add_parser("gui", help="GUI 실행 (입·표정·카메라·따라가기 탭)")

    args = ap.parse_args(argv)

    if args.cmd in (None, "gui"):
        return run_gui()

    if args.cmd == "lip":
        entries, char, cc = parse_scd(Path(args.scd), char=args.char, offset=args.offset)
        print(f"[scd] {Path(args.scd).name}  chars={dict(cc)}  char={char}  "
              f"clips={len(entries)}  shapes={dict(Counter(e[2] for e in entries))}")
        trim_end = args.trim_end
        if args.length is not None:
            trim_end = args.trim_start + args.length
        if args.trim_start or trim_end is not None:
            before = len(entries)
            entries = trim_entries(entries, start=args.trim_start, end=trim_end,
                                   rebase=not args.no_rebase)
            print(f"[trim] start={args.trim_start} end={trim_end} "
                  f"rebase={not args.no_rebase}: {before} → {len(entries)} clips")
        print(format_lip_timeline(entries, head=args.head))
        if args.analyze_only or not args.bundle:
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
            for e in ents:
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

    if args.cmd == "cam-follow":
        pos_path = args.positions
        if str(args.positions).lower().endswith(".bmarc"):   # 동작 → 위치(이 도구가 추출)
            track = extract_motion_path(args.positions, bone=args.bone, tools_dir=args.noesis)
            pos_path = (args.emit_json and args.emit_json + ".path.json") or \
                       (str(Path(args.positions).with_suffix("")) + ".path.json")
            Path(pos_path).write_text(json.dumps(track), encoding="utf-8")
            print(f"[path] bone={track['bone']} frames={len(track['frames'])} -> {pos_path}")
        if args.emit_json or not args.bundle:        # 번들 없이 카메라 JSON만 생성
            data = json.loads(Path(pos_path).read_text(encoding="utf-8"))
            pos = data.get("frames", data) if isinstance(data, dict) else data
            cam = generate_follow_camera(
                pos, view=args.view, front_dist=args.front_dist, rear_dist=args.rear_dist,
                height=args.height, lookat_height=args.lookat_height, fov=args.fov,
                threshold=args.threshold, front_yaw=args.front_yaw, smooth=args.smooth,
                start=args.start, end=args.end, length=args.length,
                rebase=not args.no_rebase)
            outp = args.emit_json or (str(Path(pos_path).with_suffix("")) + ".followcam.json")
            Path(outp).write_text(json.dumps(cam), encoding="utf-8")
            print(f"[follow] view={args.view} frames={len(cam['frames'])} -> {outp}")
            return
        out = args.out or (str(Path(args.bundle).with_suffix("")) + ".follow.unity")
        inject_follow_camera(
            Path(pos_path), Path(args.bundle), Path(out), view=args.view,
            front_dist=args.front_dist, rear_dist=args.rear_dist, height=args.height,
            lookat_height=args.lookat_height, fov=args.fov, threshold=args.threshold,
            front_yaw=args.front_yaw, smooth=args.smooth, start=args.start, end=args.end,
            length=args.length, rebase=not args.no_rebase,
            scale=args.scale, z_flip=args.z_flip, yaw180=args.yaw180)
        return


if __name__ == "__main__":
    main()
