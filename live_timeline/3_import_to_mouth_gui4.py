#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Minimal Import-to-Mouth v3.0 - 올바른 버전
기존 TimelineClip 구조를 유지하면서 3개 값만 교체
"""

import re
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox
import datetime

# SCD → SIFAS 한글자 매핑
PHONEME_MAPPING = {
    "ada": "A", "awa": "A", "ama": "A", "ara": "A", "aya": "A", "aa": "A",
    "iri": "I", "ibi": "I", "ihi": "I", "ini": "I", "isi": "I", "ii": "I",
    "uyu": "U", "ugu": "U", "uhu": "U", "uku": "U", "uru": "U", "uu": "U",
    "ebe": "E", "ede": "E", "ehe": "E", "eke": "E", "ese": "E", "ee": "E", "ere": "E",
    "odo": "O", "owo": "O", "obo": "O", "ogo": "O", "oko": "O", "oo": "O", "oso": "O",
    "nn": "N",
    "": "A",
}

LINE_RE = re.compile(r"#\s*\d+:\s*([\d.]+)s~\s*([\d.]+)s\s*\([^)]*\)\s*\[([^\]]*)\]")

def parse_analysis(path: Path):
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = LINE_RE.match(line)
        if m:
            start = float(m.group(1))
            end = float(m.group(2))
            phon = m.group(3).strip().lower()
            sifas_char = PHONEME_MAPPING.get(phon, "A")
            entries.append((start, end - start, sifas_char))
    return entries

def replace_values(entries, mouth_txt: Path, out_path: Path):
    lines = mouth_txt.read_text(encoding="utf-8").splitlines()
    out = []
    entry_idx = 0

    for line in lines:
        # m_Start 교체
        if "double m_Start =" in line and entry_idx < len(entries):
            start, dur, char = entries[entry_idx]
            out.append(f"     0 double m_Start = {start}")
        
        # m_Duration 교체
        elif "double m_Duration =" in line and entry_idx < len(entries):
            start, dur, char = entries[entry_idx]
            out.append(f"     0 double m_Duration = {dur}")
        
        # m_DisplayName 교체
        elif "string m_DisplayName =" in line and entry_idx < len(entries):
            start, dur, char = entries[entry_idx]
            out.append(f'     1 string m_DisplayName = "{char}"')
            entry_idx += 1  # 3개 값을 모두 교체했으므로 다음 엔트리로
        
        # 나머지는 그대로 유지
        else:
            out.append(line)

    out_path.write_text("\n".join(out), encoding="utf-8")
    return entry_idx

def run_gui():
    root = tk.Tk()
    root.withdraw()

    messagebox.showinfo("최소 변경 Import Tool", "1) 분석 TXT를 선택하세요")
    txt_path = Path(filedialog.askopenfilename(
        title="Select analysis TXT", filetypes=[("Text files", "*.txt")]))
    if not txt_path.exists():
        messagebox.showerror("Error", "분석 TXT가 선택되지 않았습니다")
        return

    messagebox.showinfo("최소 변경 Import Tool", "2) Mouth-CAB TXT를 선택하세요")
    mouth_path = Path(filedialog.askopenfilename(
        title="Select Mouth-CAB TXT", filetypes=[("Text files", "*.txt")]))
    if not mouth_path.exists():
        messagebox.showerror("Error", "Mouth TXT가 선택되지 않았습니다")
        return

    entries = parse_analysis(txt_path)
    if not entries:
        messagebox.showerror("Error", "TXT에서 유효한 시퀀스가 발견되지 않았습니다")
        return

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = mouth_path.with_stem(f"{mouth_path.stem}_minimal_{ts}")

    count = replace_values(entries, mouth_path, out_path)
    messagebox.showinfo("완료", f"✅ {count}개의 TimelineClip을 교체했습니다.\n\n💾 저장: {out_path}")

if __name__ == "__main__":
    run_gui()
