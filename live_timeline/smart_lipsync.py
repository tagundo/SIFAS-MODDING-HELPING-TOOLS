#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
smart_lipsync.py — SIFAC SCD 가사 → SIFAS 라이브 타임라인 입(mouth) 주입 (스마트)
================================================================================

기존 5단계(1_분석 → 2_재정렬 → 3_텍스트치환 → 4_커브정규화 → 5_UnityPy주입)를
**하나의 CLI**로 합치고, 두 가지를 개선합니다:

1. **규칙 기반 음소→모음 매핑** (화이트리스트 X)
   SIFAC 음소 코드는 ``[들어오는 모음][자음][목표 모음]`` 꼴이라, *마지막 모음*이
   입모양입니다(``oto``→O, ``usu``→U, ``ete``→E …). 기존 도구의 약 30개 화이트리스트는
   목록에 없는 코드를 전부 "A"로 떨궈 실제 곡에서 ~26%를 오매핑합니다. 규칙 기반은
   미지 코드 0%.

2. **UnityPy TypeTree 직접 편집** (텍스트 왕복 X)
   ``MemberLipSyncTrack``("Mouth")의 각 ``TimelineClip``(``m_Start``/``m_Duration``/
   ``m_DisplayName``)과, 그 클립이 참조하는 ``MemberLipSyncClip`` 플레이어블
   에셋(``index``/``weight``)을 한 번에 기입합니다.

SIFAS 입모양 테이블(실제 번들에서 확인):
    A=1  I=2  U=3  E=4  O=5  N=6   (특수: E2=13, Laugh=8)

사용:
    python3 smart_lipsync.py --scd score_0560_lyrics_buruberi_ch1.scd \\
                             --bundle 1ili3e_0.unity --out 1ili3e_0.mod.unity
    # 선택: --char N (캐릭터 id, 기본=음소가 가장 많은 리드), --weight 1.0,
    #       --track Mouth, --dry-run, --offset 0.0
"""

from __future__ import annotations
import argparse
import struct
from collections import Counter
from pathlib import Path

# --- SIFAS 입모양 ---------------------------------------------------------- #
VOWEL = {"a": "A", "i": "I", "u": "U", "e": "E", "o": "O"}
SHAPE_INDEX = {"A": 1, "I": 2, "U": 3, "E": 4, "O": 5, "N": 6, "E2": 13, "Laugh": 8}


def reduce_phoneme(code: str):
    """SIFAC 음소 코드 → SIFAS 입모양(A/I/U/E/O/N) 또는 None(무음/미지).

    일본어는 모든 모라가 모음으로 끝나므로 코드의 *마지막 모음*이 입모양.
    """
    c = (code or "").strip().lower()
    if not c:
        return None
    if c in ("nn", "n"):
        return "N"
    for ch in reversed(c):
        if ch in VOWEL:
            return VOWEL[ch]
    return None


# --- SCD(Scor) 파싱 -------------------------------------------------------- #
SCD_MAGIC = b"Scor"
ENTRY = 32
HDR = 64


def parse_scd(path: Path, char=None, offset=0.0):
    """SIFAC ``score_*_lyrics_*.scd`` → [(start_s, dur_s, shape, raw_code), ...]."""
    data = Path(path).read_bytes()
    if data[:4] != SCD_MAGIC:
        raise ValueError(f"not a Scor SCD: {path}")
    count = struct.unpack_from("<I", data, 8)[0]
    avail = (len(data) - HDR) // ENTRY
    count = min(count, avail)

    rows = []
    charcount = Counter()
    for i in range(count):
        off = HDR + i * ENTRY
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


# --- 번들 주입 ------------------------------------------------------------- #
def inject(bundle_in: Path, entries, bundle_out: Path, weight=None,
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
        if scls(t) == "MemberLipSyncTrack":
            if track_name and t.get("m_Name") != track_name:
                continue
            tracks.append((o, t))
    if not tracks:
        raise RuntimeError("MemberLipSyncTrack not found in bundle")

    report = []
    for o, t in tracks:
        clips = t.get("m_Clips", [])
        n_used = min(len(clips), len(entries))
        if verbose:
            print(f"[track] '{t.get('m_Name')}'  clips={len(clips)}  "
                  f"entries={len(entries)}  -> writing {n_used}, "
                  f"neutralizing {max(0, len(clips) - n_used)}")
        shape_hist = Counter()
        for i, clip in enumerate(clips):
            aid = clip.get("m_Asset", {}).get("m_PathID")
            pa = mb.get(aid)
            if i < len(entries):
                s, d, shape, _phon = entries[i]
                clip["m_Start"] = float(s)
                clip["m_Duration"] = float(d)
                clip["m_DisplayName"] = shape
                shape_hist[shape] += 1
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
                # leftover clip: park it off-timeline so the mouth stays closed
                clip["m_Duration"] = 0.0
                if pa is not None:
                    pt = pa.read_typetree()
                    if "weight" in pt:
                        pt["weight"] = 0.0
                    if not dry_run:
                        pa.save_typetree(pt)
        if not dry_run:
            o.save_typetree(t)
        report.append((t.get("m_Name"), n_used, dict(shape_hist)))

    if not dry_run:
        Path(bundle_out).parent.mkdir(parents=True, exist_ok=True)
        with open(bundle_out, "wb") as f:
            f.write(env.file.save(packer="lz4"))
        if verbose:
            print(f"[ok] wrote {bundle_out}")
    return report


# --- CLI ------------------------------------------------------------------- #
def main(argv=None):
    ap = argparse.ArgumentParser(description="SIFAC SCD → SIFAS mouth timeline (smart)")
    ap.add_argument("--scd", required=True, help="SIFAC score_*_lyrics_*.scd")
    ap.add_argument("--bundle", help="SIFAS live-timeline AssetBundle (omit for --analyze-only)")
    ap.add_argument("--out", help="output bundle path")
    ap.add_argument("--char", type=int, default=None, help="char_id to use (default: lead = most phonemes)")
    ap.add_argument("--weight", type=float, default=None, help="mouth intensity 0..1 (default: keep existing)")
    ap.add_argument("--offset", type=float, default=0.0, help="time offset seconds")
    ap.add_argument("--track", default=None, help="lip track m_Name (default: all MemberLipSyncTrack)")
    ap.add_argument("--analyze-only", action="store_true", help="parse SCD and print mapping, no bundle")
    ap.add_argument("--dry-run", action="store_true", help="do everything but don't write")
    args = ap.parse_args(argv)

    entries, char, charcount = parse_scd(Path(args.scd), char=args.char, offset=args.offset)
    shape_hist = Counter(e[2] for e in entries)
    print(f"[scd] {Path(args.scd).name}")
    print(f"  char ids w/ phonemes: {dict(charcount)}")
    print(f"  using char={char}  -> {len(entries)} mouth clips  shapes={dict(shape_hist)}")
    if entries[:8]:
        print("  first clips:")
        for s, d, shp, ph in entries[:8]:
            print(f"     t={s:7.3f}s dur={d:.3f}s  {shp}  (from '{ph}')")

    if args.analyze_only or not args.bundle:
        return
    out = args.out or (str(Path(args.bundle).with_suffix("")) + ".mod.unity")
    inject(Path(args.bundle), entries, Path(out),
           weight=args.weight, track_name=args.track, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
