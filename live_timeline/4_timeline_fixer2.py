#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
timeline_fixer_v2.py
- Safe, indent/newline-preserving fixes for UABEA text dumps
- Options:
  * Linearize MixIn/OutCurve (2-key, 0→1 / 1→0, slopes/weights=0, CurveMode=0)
  * Unify m_EaseIn/Out (default 0.02, clamp so ease_in+ease_out <= 0.5*duration)
  * Global time correction: t' = a + s*t on m_Start (optional)
  * Grid snap to 1e-4 (configurable)
- Creates .bak once, writes log
"""

import re
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

# ---------- Regex patterns ----------
HDR_IN  = re.compile(r"^\s*0\s*AnimationCurve\s+m_?MixInCurve\s*$",  re.IGNORECASE|re.MULTILINE)
HDR_OUT = re.compile(r"^\s*0\s*AnimationCurve\s+m_?MixOutCurve\s*$", re.IGNORECASE|re.MULTILINE)
ANCHOR_PREINF = re.compile(r"^\s*0\s*int\s+m_?PreInfinity\s*=\s*\d+\s*$", re.IGNORECASE|re.MULTILINE)
FIND_VECTOR = re.compile(r"\n(?P<indent>\s*)0\s+vector\s+m_?Curve\s*$", re.IGNORECASE)

RE_MODE_IN  = re.compile(r"(m_?BlendInCurveMode\s*=\s*)(\d+)",  re.IGNORECASE)
RE_MODE_OUT = re.compile(r"(m_?BlendOutCurveMode\s*=\s*)(\d+)", re.IGNORECASE)

RE_EASE_IN   = re.compile(r"(^\s*0\s*double\s+m_?EaseInDuration\s*=\s*)(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\s*$",  re.IGNORECASE|re.MULTILINE)
RE_EASE_OUT  = re.compile(r"(^\s*0\s*double\s+m_?EaseOutDuration\s*=\s*)(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\s*$", re.IGNORECASE|re.MULTILINE)
RE_START     = re.compile(r"(^\s*0\s*double\s+m_?Start\s*=\s*)(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\s*$",           re.IGNORECASE|re.MULTILINE)
RE_DURATION  = re.compile(r"(^\s*0\s*double\s+m_?Duration\s*=\s*)(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\s*$",        re.IGNORECASE|re.MULTILINE)

# ---------- Canonical curve blocks ----------
BLOCK_IN_LINES = [
    "0 vector m_Curve",
    " 1 Array Array (2 items)",
    "  0 int size = 2",
    "  [0]",
    "   0 Keyframe data",
    "    0 float time = 0",
    "    0 float value = 0",
    "    0 float inSlope = 0",
    "    0 float outSlope = 0",
    "    0 int weightedMode = 0",
    "    0 float inWeight = 0",
    "    0 float outWeight = 0",
    "  [1]",
    "   0 Keyframe data",
    "    0 float time = 1",
    "    0 float value = 1",
    "    0 float inSlope = 0",
    "    0 float outSlope = 0",
    "    0 int weightedMode = 0",
    "    0 float inWeight = 0",
    "    0 float outWeight = 0",
]
BLOCK_OUT_LINES = [
    "0 vector m_Curve",
    " 1 Array Array (2 items)",
    "  0 int size = 2",
    "  [0]",
    "   0 Keyframe data",
    "    0 float time = 0",
    "    0 float value = 1",
    "    0 float inSlope = 0",
    "    0 float outSlope = 0",
    "    0 int weightedMode = 0",
    "    0 float inWeight = 0",
    "    0 float outWeight = 0",
    "  [1]",
    "   0 Keyframe data",
    "    0 float time = 1",
    "    0 float value = 0",
    "    0 float inSlope = 0",
    "    0 float outSlope = 0",
    "    0 int weightedMode = 0",
    "    0 float inWeight = 0",
    "    0 float outWeight = 0",
]

def detect_line_ending(text: str) -> str:
    return "\r\n" if text.count("\r\n") >= text.count("\n")/2 else "\n"

def build_block(indent: str, lines: list[str]) -> str:
    return "\n".join(indent + ln for ln in lines)

def replace_curve_block(text: str, header_re: re.Pattern, new_lines: list[str]):
    pos = 0
    replaced = 0
    chunks = []
    while True:
        m_hdr = header_re.search(text, pos)
        if not m_hdr:
            chunks.append(text[pos:]); break
        chunks.append(text[pos:m_hdr.end()])
        m_anchor = ANCHOR_PREINF.search(text, m_hdr.end())
        if not m_anchor:
            chunks.append(text[m_hdr.end():]); break
        block_slice = text[m_hdr.end():m_anchor.start()]
        m_vec = FIND_VECTOR.search(block_slice)
        indent = m_vec.group("indent") if m_vec else "      "
        new_block = "\n" + build_block(indent, new_lines) + "\n"
        chunks.append(new_block)
        pos = m_anchor.start()
        replaced += 1
    return "".join(chunks), replaced

def round_grid(x: float, places=4):
    fmt = "{:0." + str(places) + "f}"
    return float(fmt.format(x))

def unify_ease(text: str, ease=0.02):
    def sub_in(m):  return m.group(1) + f"{ease}"
    def sub_out(m): return m.group(1) + f"{ease}"
    t1, n1 = RE_EASE_IN.subn(sub_in, text)
    t2, n2 = RE_EASE_OUT.subn(sub_out, t1)
    return t2, n1, n2

def global_time_correction(text: str, a=0.0, s=1.0, grid_places=4):
    def sub_start(m):
        v = float(m.group(2))
        vp = round_grid(a + s*v, grid_places)
        return m.group(1) + f"{vp}"
    return RE_START.sub(sub_start, text)

def clamp_ease_vs_duration(text: str):
    # one-pass: read durations, then clamp ease if needed
    lines = text.splitlines(True)
    out = []
    curr_duration = None
    for ln in lines:
        mD = RE_DURATION.match(ln)
        if mD:
            curr_duration = float(mD.group(2))
            out.append(ln); continue
        mEI = RE_EASE_IN.match(ln)
        if mEI and curr_duration is not None:
            ei = float(mEI.group(2))
            out.append(mEI.group(1) + f"{min(ei, max(0.0, 0.5*curr_duration))}\n"); continue
        mEO = RE_EASE_OUT.match(ln)
        if mEO and curr_duration is not None:
            eo = float(mEO.group(2))
            out.append(mEO.group(1) + f"{min(eo, max(0.0, 0.5*curr_duration))}\n"); continue
        out.append(ln)
    return "".join(out)

def normalize_file(path: Path, opts):
    raw = path.read_text(encoding="utf-8", errors="ignore")
    nl = detect_line_ending(raw)
    txt = raw
    rep_in = rep_out = modes = 0

    if opts["linearize_curves"]:
        txt, rep_in  = replace_curve_block(txt, HDR_IN,  BLOCK_IN_LINES)
        txt, rep_out = replace_curve_block(txt, HDR_OUT, BLOCK_OUT_LINES)
        if opts["unify_curve_modes"]:
            txt, n1 = RE_MODE_IN.subn(r"\g<1>0", txt)
            txt, n2 = RE_MODE_OUT.subn(r"\g<1>0", txt)
            modes = n1 + n2

    if opts["unify_ease"]:
        txt, n_ei, n_eo = unify_ease(txt, opts["ease_value"])

    if opts["time_correct"]:
        txt = global_time_correction(txt, opts["offset_a"], opts["scale_s"], grid_places=opts["grid_places"])

    # safety clamp
    txt = clamp_ease_vs_duration(txt)

    changed = (txt != raw)
    if changed:
        bak = path.with_suffix(path.suffix + ".bak")
        if not bak.exists():
            path.rename(bak)
        Path(path).write_text(txt.replace("\n", nl), encoding="utf-8")
    return changed, rep_in, rep_out, modes

# ---------------- GUI ----------------
def run_gui():
    root = tk.Tk()
    root.title("Timeline Fixer v2 (indent-safe)")
    root.geometry("560x360")

    linearize_var = tk.IntVar(value=1)
    modes_var     = tk.IntVar(value=1)
    ease_var      = tk.IntVar(value=1)
    ease_val      = tk.StringVar(value="0.02")

    tfix_var      = tk.IntVar(value=0)
    a_val         = tk.StringVar(value="0.0")
    s_val         = tk.StringVar(value="1.0")
    grid_places   = tk.StringVar(value="4")

    def process(paths):
        logs=[]; total=(0,0,0,0)
        for p in paths:
            try:
                opts = dict(
                    linearize_curves=bool(linearize_var.get()),
                    unify_curve_modes=bool(modes_var.get()),
                    unify_ease=bool(ease_var.get()),
                    ease_value=float(ease_val.get()),
                    time_correct=bool(tfix_var.get()),
                    offset_a=float(a_val.get()),
                    scale_s=float(s_val.get()),
                    grid_places=int(grid_places.get()),
                )
                ch, rin, rout, md = normalize_file(Path(p), opts)
                total = (total[0]+(1 if ch else 0), total[1]+rin, total[2]+rout, total[3]+md)
                logs.append(f"[OK] {Path(p).name} changed={ch} MixIn={rin} MixOut={rout} modes={md}")
            except Exception as e:
                logs.append(f"[FAIL] {Path(p).name} -> {e}")
        summary = [
            f"Modified files: {total[0]}",
            f"Replaced MixIn: {total[1]}",
            f"Replaced MixOut: {total[2]}",
            f"Curve modes set: {total[3]}",
            ""
        ]
        top = tk.Toplevel(root); top.title("Result"); top.geometry("1000x650")
        txt = tk.Text(top, wrap="none"); txt.pack(fill="both", expand=True)
        txt.insert("end", "\n".join(summary+logs)); txt.configure(state="disabled")

    def pick_files():
        files = filedialog.askopenfilenames(title="Select UABEA text dumps", filetypes=[("Text dumps","*.txt"),("All","*.*")])
        if files: process(files)

    def pick_folder():
        d = filedialog.askdirectory(title="Select folder (recursive)")
        if not d: return
        paths = [str(p) for p in Path(d).rglob("*.txt")]
        if paths: process(paths)
        else: messagebox.showerror("오류", "대상 텍스트 덤프가 없습니다")

    frm = ttk.Frame(root); frm.pack(fill="both", expand=True, padx=12, pady=12)

    ttk.Checkbutton(frm, text="Linearize MixIn/OutCurve (2-key)", variable=linearize_var).pack(anchor="w")
    ttk.Checkbutton(frm, text="Set m_BlendIn/OutCurveMode=0",     variable=modes_var).pack(anchor="w")

    row = ttk.Frame(frm); row.pack(fill="x", pady=4)
    ttk.Checkbutton(row, text="Unify EaseIn/Out to", variable=ease_var).pack(side="left")
    ttk.Entry(row, textvariable=ease_val, width=8).pack(side="left", padx=6)

    row2 = ttk.Frame(frm); row2.pack(fill="x", pady=4)
    ttk.Checkbutton(row2, text="Global time correction t' = a + s*t", variable=tfix_var).pack(side="left")
    ttk.Label(row2, text="a=").pack(side="left"); ttk.Entry(row2, textvariable=a_val, width=8).pack(side="left", padx=4)
    ttk.Label(row2, text="s=").pack(side="left"); ttk.Entry(row2, textvariable=s_val, width=8).pack(side="left", padx=4)
    ttk.Label(row2, text="grid places=").pack(side="left"); ttk.Entry(row2, textvariable=grid_places, width=4).pack(side="left", padx=4)

    ttk.Button(frm, text="파일 선택(복수)", command=pick_files).pack(fill="x", pady=6)
    ttk.Button(frm, text="폴더 선택(재귀)", command=pick_folder).pack(fill="x", pady=6)
    root.mainloop()

if __name__ == "__main__":
    run_gui()
