#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SIFAC SCD Lyrics 분석기 v4.0
- score_XXXX_lyrics_XXXX_chX.scd 전용
- 엔트리 구조(32B):
  0-1:  seq (uint16)
  2-3:  type (uint16, 보통 0x0004)
  4-7:  start_ms (uint32)
  8-15: padding (8B)
  16-19: dur_ms (uint32)
  20:   char_id (uint8)
  21-23: phoneme (3B ASCII, 예: ada/iri/nn/uyu)
  24-31: padding (8B)
"""

import argparse
import os
import glob
import struct
from pathlib import Path
from typing import List, Dict, Tuple

ENTRY_SIZE = 32
HEADER_SIZE = 64
MAGIC = b"Scor"

def read_u16_le(b: bytes, off: int) -> int:
    return struct.unpack_from("<H", b, off)[0]

def read_u32_le(b: bytes, off: int) -> int:
    return struct.unpack_from("<I", b, off)[0]

def safe_ascii_3(b: bytes) -> str:
    # 3바이트 phoneme를 ASCII로 안전하게 디코드 후 널 제거
    s = b.decode("ascii", errors="ignore")
    return s.replace("\x00", "")

def format_sec(ms: int) -> str:
    return f"{ms/1000.0:5.2f}s"

def parse_file(path: Path) -> Dict:
    data = path.read_bytes()
    if len(data) < HEADER_SIZE:
        raise ValueError("파일 크기가 너무 작습니다(헤더 미만).")
    if data[:4] != MAGIC:
        raise ValueError("매직 헤더가 'Scor'가 아닙니다.")

    file_size = read_u32_le(data, 4)
    entry_count = read_u32_le(data, 8)
    # 부가 헤더값들
    unk_12_15 = read_u32_le(data, 12)
    unk_16_19 = read_u32_le(data, 16)
    unk_20_23 = read_u32_le(data, 20)
    unk_24_27 = read_u32_le(data, 24)
    channel    = read_u32_le(data, 28)

    # 기대 크기(헤더 + 엔트리*32) 검증(넘치거나 모자랄 수 있으므로 하한만 확인)
    expected_min = HEADER_SIZE + entry_count * ENTRY_SIZE
    if len(data) < expected_min:
        # 일부 덜 쓰여진 파일 허용: available 엔트리만 읽음
        entry_count = max(0, (len(data) - HEADER_SIZE) // ENTRY_SIZE)

    entries = []
    base = HEADER_SIZE
    for i in range(entry_count):
        off = base + i * ENTRY_SIZE
        chunk = data[off:off+ENTRY_SIZE]
        if len(chunk) < ENTRY_SIZE:
            break

        seq = read_u16_le(chunk, 0)
        typ = read_u16_le(chunk, 2)
        start_ms = read_u32_le(chunk, 4)
        # 8-15 padding skip
        dur_ms = read_u32_le(chunk, 16)
        char_id = chunk[20]
        phoneme = safe_ascii_3(chunk[21:24]).strip()

        entries.append({
            "seq": seq,
            "type": typ,
            "start_ms": start_ms,
            "dur_ms": dur_ms,
            "char_id": char_id,
            "phoneme": phoneme,
        })

    return {
        "path": str(path),
        "file_size_hdr": file_size,
        "channel": channel,
        "hdr_extra": (unk_12_15, unk_16_19, unk_20_23, unk_24_27),
        "entries": entries,
    }

def group_by_time(entries: List[Dict]) -> List[Dict]:
    """
    timing+duration+phoneme 기준으로 병합.
    char_id 목록을 모으고 seq는 최소/최대로 요약.
    """
    groups: Dict[Tuple[int,int,str], Dict] = {}
    for e in entries:
        key = (e["start_ms"], e["dur_ms"], e["phoneme"])
        g = groups.get(key)
        if not g:
            groups[key] = {
                "start_ms": e["start_ms"],
                "dur_ms": e["dur_ms"],
                "phoneme": e["phoneme"],
                "char_ids": {e["char_id"]},
                "seq_min": e["seq"],
                "seq_max": e["seq"],
            }
        else:
            g["char_ids"].add(e["char_id"])
            if e["seq"] < g["seq_min"]: g["seq_min"] = e["seq"]
            if e["seq"] > g["seq_max"]: g["seq_max"] = e["seq"]

    out = list(groups.values())
    out.sort(key=lambda x: (x["start_ms"], x["dur_ms"], x["phoneme"]))
    return out

def render_report(meta: Dict, merge: bool, max_preview: int = 500) -> str:
    path = meta["path"]
    file_size_hdr = meta["file_size_hdr"]
    channel = meta["channel"]
    hdr_extra = meta["hdr_extra"]
    entries = meta["entries"]

    lines = []
    lines.append(f"=== SIFAC Lyrics SCD 분석 v4.0 ===")
    lines.append(f"파일: {path}")
    lines.append(f"헤더 파일 크기: {file_size_hdr} bytes")
    lines.append(f"채널: {channel}, 기타 헤더: {hdr_extra}")
    lines.append(f"엔트리 수: {len(entries)}")
    lines.append("")

    # 원본(캐릭터별) 프리뷰
    lines.append(f"--- 캐릭터별 시퀀스 (처음 {min(max_preview,len(entries))}개) ---")
    for e in sorted(entries, key=lambda x: (x["start_ms"], x["char_id"]))[:max_preview]:
        s = e["start_ms"]; d = e["dur_ms"]; end = s + d
        phon = e["phoneme"] if e["phoneme"] else ""
        lines.append(
            f"# {e['seq']:4d}: {format_sec(s)}~{format_sec(end)} ({format_sec(d)}) "
            f"[{phon}] char={e['char_id']}"
        )

    # 병합 출력
    if merge:
        lines.append("")
        lines.append(f"--- 병합 출력 (timing+duration+phoneme 기준) ---")
        groups = group_by_time(entries)
        for g in groups:
            s = g["start_ms"]; d = g["dur_ms"]; end = s + d
            phon = g["phoneme"] if g["phoneme"] else ""
            chars = ",".join(str(c) for c in sorted(g["char_ids"]))
            seq_span = f"{g['seq_min']}" if g["seq_min"] == g["seq_max"] else f"{g['seq_min']}-{g['seq_max']}"
            lines.append(
                f"seq[{seq_span}]: {format_sec(s)}~{format_sec(end)} ({format_sec(d)}) "
                f"[{phon}] chars={{{{ {chars} }}}}"
            )

    # 간단 통계
    lines.append("")
    lines.append("--- 통계 ---")
    total_ms = 0
    if entries:
        starts = [e["start_ms"] for e in entries]
        ends   = [e["start_ms"]+e["dur_ms"] for e in entries]
        total_ms = max(ends) - min(starts)
    unique_ph = sorted(set(e["phoneme"] for e in entries if e["phoneme"]))
    lines.append(f"총 구간 길이(대략): {format_sec(total_ms)}")
    lines.append(f"고유 phoneme: {len(unique_ph)}개 -> {', '.join(unique_ph) if unique_ph else '(없음)'}")

    return "\n".join(lines)

def write_report(path: Path, text: str) -> Path:
    out = path.with_suffix("")  # strip .scd
    out = Path(str(out) + "_lyrics_analysis_v4.txt")
    out.write_text(text, encoding="utf-8")
    return out

def analyze_one(path: Path, merge: bool) -> None:
    meta = parse_file(path)
    report = render_report(meta, merge=merge)
    print(report)
    out = write_report(path, report)
    print(f"\n📁 결과 저장: {out}")

def auto_mode(merge: bool) -> None:
    patterns = ["*lyrics*.scd", "*facial*.scd", "*lip*.scd", "*voice*.scd"]
    files = []
    for p in patterns:
        files.extend(glob.glob(p))
    files = sorted(set(files))
    if not files:
        print("현재 폴더에 lyrics/facial SCD 파일이 없습니다.")
        return
    print(f"발견: {len(files)}개 파일")
    for f in files:
        print(f"- {f}")
    print("")
    for f in files:
        print("="*80)
        print(f"분석: {f}")
        print("="*80)
        analyze_one(Path(f), merge=merge)
        print("")

def main():
    ap = argparse.ArgumentParser(description="SIFAC SCD Lyrics 분석기 v4.0")
    ap.add_argument("file", nargs="?", help="분석할 .scd 파일 경로")
    ap.add_argument("--auto", action="store_true", help="현재 폴더의 lyrics 관련 SCD를 자동 분석")
    ap.add_argument("--merge", action="store_true", help="동일 타임스탬프/지속/phoneme를 병합 출력")
    args = ap.parse_args()

    if args.auto:
        auto_mode(merge=args.merge)
    elif args.file:
        analyze_one(Path(args.file), merge=args.merge)
    else:
        ap.print_help()

if __name__ == "__main__":
    main()
