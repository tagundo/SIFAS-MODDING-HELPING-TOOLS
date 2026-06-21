#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
facial_inject.py — SIFAS 라이브 타임라인에 표정(눈/시선/볼) 주입
================================================================

립싱크(``smart_lipsync.py``)와 같은 방식으로, SIFAS 라이브 번들의 표정 트랙을
UnityPy TypeTree 로 **직접 편집**합니다. 입과 달리 SIFAC 쪽에 깔끔한 소스가 없어,
**이름으로 지정하는 표정 스크립트** + **자동 눈깜빡임** 으로 손쉽게 작성합니다.

대상 트랙(실제 번들에서 확인):
  * ``MemberEyeTrack "Eye"``   클립 → ``MemberEyeClip``  (index, weight)
  * ``MemberGazeTrack "Gaze"`` 클립 → ``MemberGazeClip`` (target, weightForDirection)
  * ``MemberCheekTrack "Cheek"`` 클립 → ``MemberCheekClip`` (볼터치 on/off)

표정 이름 ↔ 값 테이블(실제 번들에서 확인):
  Eye :  Close=1 Closish=2 Open=3 WideOpen=4 Close_Smile=5
         WinkR=12 WinkL=13 Trouble=14 Sad=15 Angry=16 Missing=18
  Gaze:  Camera=21 Audience=22 Up=31 Down=32 Left=33 Right=34
  Cheek: Ppo (볼터치)

스크립트 형식(텍스트, 한 줄 = 한 클립; '#' 주석):
    <track> <start_s> <dur_s> <name> [weight]
    eye   0.0   2.0  Close      1.0
    eye   35.2  0.37 WinkR      1.0
    gaze  1.97  4.3  Camera     1.0
    gaze  14.75 1.07 Audience   1.0
    cheek 20.76 0.82 Ppo

사용:
    python3 facial_inject.py --script faces.txt --bundle 1ili3e_0.unity --out out.unity
    python3 facial_inject.py --auto-blink --bundle 1ili3e_0.unity --out out.unity
    python3 facial_inject.py --list-names          # 표정 이름 목록만 출력
"""

from __future__ import annotations
import argparse
import random
from pathlib import Path

# --- 표정 테이블 ----------------------------------------------------------- #
EYE = {"Close": 1, "Closish": 2, "Open": 3, "WideOpen": 4, "Close_Smile": 5,
       "WinkR": 12, "WinkL": 13, "Trouble": 14, "Sad": 15, "Angry": 16, "Missing": 18}
GAZE = {"Camera": 21, "Audience": 22, "Up": 31, "Down": 32, "Left": 33, "Right": 34}
CHEEK = {"Ppo"}

TRACK_CLASS = {
    "eye":   ("MemberEyeTrack",   "index", EYE),
    "gaze":  ("MemberGazeTrack",  "target", GAZE),
    "cheek": ("MemberCheekTrack", None, None),   # cheek 에셋엔 index 없음(이름만)
}
WEIGHT_FIELD = {"eye": "weight", "gaze": "weightForDirection", "cheek": "weight"}


# --- 스크립트 파싱 --------------------------------------------------------- #
class Entry:
    __slots__ = ("track", "start", "dur", "name", "weight")

    def __init__(self, track, start, dur, name, weight):
        self.track, self.start, self.dur, self.name, self.weight = track, start, dur, name, weight


def parse_script(path: Path):
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
        start = float(parts[1]); dur = float(parts[2]); name = parts[3]
        weight = float(parts[4]) if len(parts) > 4 else 1.0
        _validate(track, name)
        entries.append(Entry(track, start, dur, name, weight))
    return entries


def _validate(track, name):
    if track == "eye" and name not in EYE:
        raise ValueError(f"unknown eye '{name}'; valid: {', '.join(EYE)}")
    if track == "gaze" and name not in GAZE:
        raise ValueError(f"unknown gaze '{name}'; valid: {', '.join(GAZE)}")
    if track == "cheek" and name not in CHEEK:
        raise ValueError(f"unknown cheek '{name}'; valid: {', '.join(CHEEK)}")


def auto_blink(duration=125.0, period=3.5, jitter=1.2, blink=0.16, seed=0):
    """주기적 자연 눈깜빡임(Close) 엔트리 생성."""
    rng = random.Random(seed)
    t = 1.0
    out = []
    while t < duration:
        out.append(Entry("eye", round(t, 3), blink, "Close", 1.0))
        t += period + rng.uniform(-jitter, jitter)
    return out


# --- 번들 주입 ------------------------------------------------------------- #
def inject(bundle_in: Path, entries, bundle_out: Path, dry_run=False, verbose=True):
    import UnityPy
    env = UnityPy.load(str(bundle_in))
    objs = list(env.objects)
    smap = {o.path_id: o.read().m_Name for o in objs if o.type.name == "MonoScript"}

    def scls(t):
        return smap.get(t.get("m_Script", {}).get("m_PathID"))

    mb = {o.path_id: o for o in objs if o.type.name == "MonoBehaviour"}

    # group entries by track kind
    by_track = {"eye": [], "gaze": [], "cheek": []}
    for e in entries:
        by_track[e.track].append(e)
    for k in by_track:
        by_track[k].sort(key=lambda e: e.start)

    report = []
    for kind, (cls, idx_field, table) in TRACK_CLASS.items():
        ents = by_track[kind]
        if not ents:
            continue
        track_objs = [o for o in objs if o.type.name == "MonoBehaviour" and scls(o.read_typetree()) == cls]
        if not track_objs:
            if verbose:
                print(f"[warn] {cls} not in bundle; skipping {len(ents)} {kind} entries")
            continue
        o = track_objs[0]
        t = o.read_typetree()
        clips = t.get("m_Clips", [])
        n_used = min(len(clips), len(ents))
        if len(ents) > len(clips) and verbose:
            print(f"[warn] {kind}: {len(ents)} entries but only {len(clips)} clip slots; "
                  f"writing first {len(clips)}")
        wfield = WEIGHT_FIELD[kind]
        for i, clip in enumerate(clips):
            aid = clip.get("m_Asset", {}).get("m_PathID")
            pa = mb.get(aid)
            if i < len(ents):
                e = ents[i]
                clip["m_Start"] = float(e.start)
                clip["m_Duration"] = float(e.dur)
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
                clip["m_Duration"] = 0.0  # park leftover
                if pa is not None:
                    pt = pa.read_typetree()
                    if wfield in pt:
                        pt[wfield] = 0.0
                    if not dry_run:
                        pa.save_typetree(pt)
        if not dry_run:
            o.save_typetree(t)
        report.append((kind, cls, n_used, len(clips)))
        if verbose:
            print(f"[track] {cls}: wrote {n_used}/{len(clips)} clips ({kind})")

    if not dry_run:
        Path(bundle_out).parent.mkdir(parents=True, exist_ok=True)
        with open(bundle_out, "wb") as f:
            f.write(env.file.save(packer="lz4"))
        if verbose:
            print(f"[ok] wrote {bundle_out}")
    return report


# --- CLI ------------------------------------------------------------------- #
def main(argv=None):
    ap = argparse.ArgumentParser(description="Inject facial (eye/gaze/cheek) into a SIFAS live bundle")
    ap.add_argument("--script", help="expression script (text)")
    ap.add_argument("--auto-blink", action="store_true", help="generate periodic natural blinks")
    ap.add_argument("--blink-period", type=float, default=3.5)
    ap.add_argument("--duration", type=float, default=125.0, help="song length for --auto-blink")
    ap.add_argument("--bundle", help="SIFAS live-timeline AssetBundle")
    ap.add_argument("--out", help="output bundle path")
    ap.add_argument("--list-names", action="store_true", help="print valid expression names and exit")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    if args.list_names:
        print("eye  :", ", ".join(EYE))
        print("gaze :", ", ".join(GAZE))
        print("cheek:", ", ".join(CHEEK))
        return

    entries = []
    if args.script:
        entries += parse_script(Path(args.script))
    if args.auto_blink:
        entries += auto_blink(duration=args.duration, period=args.blink_period)
    if not entries:
        ap.error("nothing to do: pass --script and/or --auto-blink")

    from collections import Counter
    print(f"[entries] {len(entries)}  by track: {dict(Counter(e.track for e in entries))}")
    if not args.bundle:
        for e in entries[:12]:
            print(f"   {e.track:5} t={e.start:7.3f} dur={e.dur:.3f} {e.name} w={e.weight}")
        return
    out = args.out or (str(Path(args.bundle).with_suffix("")) + ".face.unity")
    inject(Path(args.bundle), entries, Path(out), dry_run=args.dry_run)


if __name__ == "__main__":
    main()
