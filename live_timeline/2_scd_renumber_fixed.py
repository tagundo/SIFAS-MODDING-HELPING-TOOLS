#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SCD 분석 파일 재정렬 도구 v2.0 (수정됨)
캐릭터별 시퀀스에서 일부 항목을 삭제한 후 번호와 개수를 자동으로 재정렬
시퀀스 데이터를 제대로 유지하면서 재정렬
"""

import re
import argparse
from pathlib import Path
from typing import List, Dict

def renumber_analysis_file_fixed(input_file: Path, output_file: Path = None) -> None:
    """분석 파일의 시퀀스 번호와 개수를 자동으로 재정렬 (수정된 버전)"""
    
    print(f"📖 Reading file: {input_file}")
    
    with open(input_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    lines = content.split('\n')
    print(f"📄 Total lines: {len(lines)}")
    
    # 캐릭터별 시퀀스 섹션 찾기
    sequence_start = -1
    sequence_end = -1
    
    for i, line in enumerate(lines):
        if "캐릭터별 시퀀스" in line and "---" in line:
            sequence_start = i
            print(f"🔍 Found sequence section start at line {i+1}: {line.strip()}")
        elif sequence_start != -1 and line.startswith("---") and "캐릭터별 시퀀스" not in line:
            sequence_end = i
            print(f"🔍 Found sequence section end at line {i+1}: {line.strip()}")
            break
    
    if sequence_start == -1:
        print("❌ '캐릭터별 시퀀스' 섹션을 찾을 수 없습니다.")
        return
    
    if sequence_end == -1:
        # 파일 끝까지 시퀀스 섹션
        for i in range(len(lines) - 1, sequence_start, -1):
            if lines[i].strip() and not lines[i].startswith('#'):
                sequence_end = i + 1
                break
        if sequence_end == -1:
            sequence_end = len(lines)
    
    print(f"📊 Sequence section: lines {sequence_start+1} ~ {sequence_end}")
    
    # 시퀀스 라인들 추출
    sequence_entries = []
    
    # 시퀀스 패턴: #  123:   1.23s~  4.56s (3.33s) [ada] char=1
    sequence_pattern = r'^#\s*(\d+):\s*(\d+\.?\d*)s~\s*(\d+\.?\d*)s\s*\(([^)]+)\)\s*\[([^\]]*)\]\s*char=(\d+)\s*$'
    
    for i in range(sequence_start + 1, sequence_end):
        line = lines[i].strip()
        if not line:
            continue
            
        match = re.match(sequence_pattern, line)
        if match:
            old_seq = int(match.group(1))
            start_sec = float(match.group(2))
            end_sec = float(match.group(3))
            duration_str = match.group(4)
            phoneme = match.group(5)
            char_id = int(match.group(6))
            
            sequence_entries.append({
                'old_seq': old_seq,
                'start_sec': start_sec,
                'end_sec': end_sec,
                'duration_str': duration_str,
                'phoneme': phoneme,
                'char_id': char_id,
                'start_str': match.group(2),
                'end_str': match.group(3)
            })
        else:
            print(f"⚠️  Line {i+1} doesn't match pattern: {line}")
    
    if not sequence_entries:
        print("❌ 시퀀스 엔트리를 찾을 수 없습니다.")
        return
    
    print(f"✅ Found {len(sequence_entries)} sequence entries")
    
    # 시간순으로 정렬
    sequence_entries.sort(key=lambda x: (x['start_sec'], x['char_id']))
    
    # 새로운 파일 구성
    new_lines = []
    
    # 시퀀스 섹션 이전 부분
    for i in range(sequence_start):
        new_lines.append(lines[i])
    
    # 새로운 시퀀스 섹션 헤더
    new_lines.append(f"--- 캐릭터별 시퀀스 ({len(sequence_entries)}개) ---")
    
    # 재정렬된 시퀀스들
    for new_seq, entry in enumerate(sequence_entries, 1):
        new_line = f"# {new_seq:4d}: {entry['start_str']:>6s}s~ {entry['end_str']:>6s}s ({entry['duration_str']}) [{entry['phoneme']}] char={entry['char_id']}"
        new_lines.append(new_line)
    
    # 시퀀스 섹션 이후 부분
    for i in range(sequence_end, len(lines)):
        line = lines[i]
        # 엔트리 수 정보 업데이트
        if "엔트리 수:" in line:
            line = re.sub(r'엔트리 수: \d+', f'엔트리 수: {len(sequence_entries)}', line)
        new_lines.append(line)
    
    # 출력 파일 결정
    if output_file is None:
        output_file = input_file.with_stem(f"{input_file.stem}_renumbered")
    
    # 결과 저장
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(new_lines))
    
    print(f"✅ 재정렬된 파일 저장: {output_file}")
    
    # 통계 출력
    print(f"\n📈 재정렬 통계:")
    print(f"   총 시퀀스: {len(sequence_entries)}개")
    print(f"   시간 범위: {min(e['start_sec'] for e in sequence_entries):.2f}s ~ {max(e['end_sec'] for e in sequence_entries):.2f}s")
    
    # 캐릭터별 통계
    char_stats = {}
    for entry in sequence_entries:
        char_id = entry['char_id']
        char_stats[char_id] = char_stats.get(char_id, 0) + 1
    
    print(f"   캐릭터별 분포:")
    for char_id in sorted(char_stats.keys()):
        count = char_stats[char_id]
        print(f"     char={char_id}: {count:3d}개")
    
    # 음성학별 통계
    phoneme_stats = {}
    for entry in sequence_entries:
        phoneme = entry['phoneme']
        if phoneme:  # 빈 음성학 제외
            phoneme_stats[phoneme] = phoneme_stats.get(phoneme, 0) + 1
    
    if phoneme_stats:
        print(f"   주요 음성학 (상위 10개):")
        sorted_phonemes = sorted(phoneme_stats.items(), key=lambda x: x[1], reverse=True)
        for phoneme, count in sorted_phonemes[:10]:
            print(f"     [{phoneme:>3s}]: {count:3d}개")

def interactive_mode():
    """대화형 모드"""
    print("🎵 SCD 분석 파일 재정렬 도구 v2.0")
    print("=" * 50)
    
    while True:
        input_path = input("📁 입력 파일 경로를 입력하세요 (또는 'q' 종료): ").strip()
        
        if input_path.lower() == 'q':
            break
            
        if not input_path:
            continue
            
        input_file = Path(input_path)
        
        if not input_file.exists():
            print(f"❌ 파일을 찾을 수 없습니다: {input_file}")
            continue
        
        output_choice = input("📤 출력 파일명 (엔터시 자동 생성): ").strip()
        output_file = Path(output_choice) if output_choice else None
        
        try:
            renumber_analysis_file_fixed(input_file, output_file)
            print("🎉 재정렬 완료!\n")
            
        except Exception as e:
            print(f"❌ 오류 발생: {str(e)}")
            import traceback
            traceback.print_exc()

def main():
    parser = argparse.ArgumentParser(description="SCD 분석 파일 재정렬 도구 v2.0")
    parser.add_argument("input_file", nargs='?', help="입력 분석 파일")
    parser.add_argument("-o", "--output", help="출력 파일 (생략시 자동 생성)")
    parser.add_argument("-i", "--interactive", action="store_true", help="대화형 모드")
    
    args = parser.parse_args()
    
    if args.interactive or not args.input_file:
        interactive_mode()
        return
    
    input_file = Path(args.input_file)
    output_file = Path(args.output) if args.output else None
    
    if not input_file.exists():
        print(f"❌ 입력 파일을 찾을 수 없습니다: {input_file}")
        return
    
    try:
        renumber_analysis_file_fixed(input_file, output_file)
        print(f"\n🎉 재정렬 완료!")
        
    except Exception as e:
        print(f"❌ 재정렬 실패: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()