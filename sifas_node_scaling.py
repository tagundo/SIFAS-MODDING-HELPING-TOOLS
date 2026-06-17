#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SIFAS NodeScaling Editor — LiveCoreMemberNodeScaling 편집/수리 도구
==================================================================
`LiveCoreMemberNodeScaling` (LLAS.Scene.Live.Components) 은 멤버가 라이브에
등장할 때 지정한 본의 로컬 위치/스케일을 캐릭터별 체형값(`scaledValue`)으로
덮어쓰는 런타임 컴포넌트다. 각 항목은 모델이 기본으로 가진 값(`originValue`)도
함께 들고 있어서, 정상 번들의 불변식은 다음과 같다.

      bone.localPosition == positionValue.originValue
      bone.localScale    == scaleValue.originValue

FBX 왕복/이식 파이프라인이 본을 옮겨 놓으면 originValue 가 실제 본과 어긋나고,
런타임에 컴포넌트가 scaledValue 를 강제하면서 본이 '순간이동'한다(예: 세일러
리본이 목→가슴으로 흘러내림). 정적 뷰어에서는 안 보인다.

이 도구가 하는 일
-----------------
- 번들 안의 모든 NodeScaling 항목을 스캔: 본 이름, 종류(pos/scale),
  originValue, scaledValue, 현재 본의 로컬값, 일치 여부(status)를 표로 표시.
- 일괄 수리 두 가지:
    * Re-anchor (rebase) : 본이 옮겨졌을 때 origin 을 새 로컬값으로 다시 잡고
      체형 보정량(위치=덧셈 offset, 스케일=곱셈 ratio)은 그대로 보존한다.
      → 체형 보정 기능을 유지하면서 순간이동만 없앤다. (transplant 권장)
    * Neutralize         : origin=scaled=현재 로컬값으로 만들어 오버라이드를
      완전한 no-op 으로 바꾼다. origin 자체를 신뢰할 수 없는 import 결과용.
- 수동 편집: 각 항목의 originValue/scaledValue, 컴포넌트의 heightScale 직접 수정.
- 새 부위 추가: 스켈레톤의 아무 본이나 골라 position/scale 보정 항목을 새로 만든다
  (origin 은 본의 현재 local 값으로 자동, scaled 만 지정하면 됨). 예: 허벅지·허리·
  팔 두께를 런타임에 키우거나 줄이기. 이미 있는 본을 고르면 추가 대신 갱신한다.
- 일치하는(건강한) 항목은 건드리지 않아 안전하고 멱등.

UI 언어는 영어. 실행 환경 자동 감지: 데스크톱 → Tkinter GUI / 헤드리스 → 텍스트 메뉴(+CLI).
의존성: UnityPy. 검증: Unity 2018.4 SIFAS 모델팩.
"""

import os
import sys
import argparse
import importlib
import subprocess
from pathlib import Path


# ==========================================================================
# 0. 의존성 자동 설치
# ==========================================================================
def ensure_module(import_name, pip_name=None):
    try:
        return importlib.import_module(import_name)
    except ImportError:
        pip_name = pip_name or import_name
        print(f"[setup] installing '{pip_name}' ...")
        cmd = [sys.executable, "-m", "pip", "install", pip_name]
        try:
            subprocess.run(cmd + ["--break-system-packages", "-q"], check=True)
        except subprocess.CalledProcessError:
            subprocess.run(cmd + ["-q"], check=True)
        return importlib.import_module(import_name)


UnityPy = ensure_module("UnityPy")


# ==========================================================================
# 1. NodeScaling 모델
# ==========================================================================
def _is_node_scaling(mb):
    return "targetName" in mb and "scaleValues" in mb and "positionValues" in mb


def _v3(d):
    return (float(d["x"]), float(d["y"]), float(d["z"]))


def _d3(t):
    return {"x": float(t[0]), "y": float(t[1]), "z": float(t[2])}


def _dist(a, b):
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]), abs(a[2] - b[2]))


class Entry:
    """NodeScaling 항목 1개 (위치 또는 스케일 오버라이드)."""
    __slots__ = ("comp_index", "target_name", "kind", "index", "bone",
                 "origin", "scaled", "local", "missing")

    def __init__(self, comp_index, target_name, kind, index, bone,
                 origin, scaled, local, missing):
        self.comp_index = comp_index      # 몇 번째 NodeScaling 컴포넌트인지
        self.target_name = target_name    # targetName (예: ch0107_co0002_body)
        self.kind = kind                  # "pos" | "scale"
        self.index = index                # positionValues/scaleValues 내 인덱스
        self.bone = bone                  # 타깃 본 이름 (없으면 "<MISSING>")
        self.origin = origin              # (x,y,z)
        self.scaled = scaled              # (x,y,z)
        self.local = local                # 현재 본 로컬값 (x,y,z) or None
        self.missing = missing            # 타깃 Transform 이 사라졌는가

    @property
    def consistent(self):
        return self.local is not None and _dist(self.origin, self.local) <= 1e-3

    def status(self):
        if self.missing:
            return "MISSING"
        return "ok" if self.consistent else "MISMATCH"


def _go_name_map(env):
    return {o.path_id: o.read_typetree().get("m_Name")
            for o in env.objects if o.type.name == "GameObject"}


def bone_catalog(env):
    """스켈레톤의 모든 본 → [(name, transform_pid, localPos, localScale)] 이름순.
    NodeScaling 에 새 항목을 추가할 때 타깃 본을 고르는 데 쓴다."""
    go = _go_name_map(env)
    out = {}
    for o in env.objects:
        if o.type.name != "Transform":
            continue
        t = o.read_typetree()
        nm = go.get(t.get("m_GameObject", {}).get("m_PathID"))
        if not nm or nm in out:
            continue
        out[nm] = (o.path_id, _v3(t["m_LocalPosition"]), _v3(t["m_LocalScale"]))
    return [(nm, *v) for nm, v in sorted(out.items())]


def _bone_pid_map(env):
    go = _go_name_map(env)
    m = {}
    for o in env.objects:
        if o.type.name == "Transform":
            nm = go.get(o.read_typetree().get("m_GameObject", {}).get("m_PathID"))
            if nm and nm not in m:
                m[nm] = o.path_id
    return m


def _transform_local(obj, kind):
    """Transform 의 localPosition(pos) 또는 localScale(scale) → (x,y,z)."""
    t = obj.read_typetree()
    key = "m_LocalPosition" if kind == "pos" else "m_LocalScale"
    return _v3(t[key]), t


def scan_components(env):
    """(components, entries) 반환.
    components = [(obj, mb, targetName, heightScale)]   (편집 시 mb 를 다시 읽음)
    entries = [Entry, ...]"""
    objs = list(env.objects)
    uid = {o.path_id: o for o in objs}
    go = _go_name_map(env)

    def bone_of(pid):
        o = uid.get(pid)
        if not o or o.type.name != "Transform":
            return None, None
        t = o.read_typetree()
        return go.get(t.get("m_GameObject", {}).get("m_PathID")), o

    comps, entries = [], []
    ci = 0
    for o in objs:
        if o.type.name != "MonoBehaviour":
            continue
        mb = o.read_typetree()
        if not _is_node_scaling(mb):
            continue
        comps.append((o, mb, mb.get("targetName", "?"), float(mb.get("heightScale", 1.0))))
        for kind, listkey in (("pos", "positionValues"), ("scale", "scaleValues")):
            for i, ev in enumerate(mb.get(listkey, [])):
                bn, bobj = bone_of(ev["target"]["m_PathID"])
                local = None
                if bobj is not None:
                    local, _ = _transform_local(bobj, kind)
                entries.append(Entry(ci, mb.get("targetName", "?"), kind, i,
                                     bn or "<MISSING>", _v3(ev["originValue"]),
                                     _v3(ev["scaledValue"]), local, bobj is None))
        ci += 1
    return comps, entries


# ==========================================================================
# 2. 수리 연산 (in-memory entry 값 계산)
# ==========================================================================
def rebase_values(origin, scaled, local, kind):
    """본이 옮겨졌을 때 origin 을 local 로 재앵커하되 보정량은 보존.
    위치: 덧셈 offset(scaled-origin) 유지 / 스케일: 곱셈 ratio(scaled/origin) 유지."""
    if local is None:
        return origin, scaled
    if kind == "pos":
        delta = tuple(scaled[k] - origin[k] for k in range(3))
        return tuple(local), tuple(local[k] + delta[k] for k in range(3))
    ratio = tuple((scaled[k] / origin[k] if abs(origin[k]) > 1e-9 else 1.0) for k in range(3))
    return tuple(local), tuple(local[k] * ratio[k] for k in range(3))


def neutralize_values(local):
    """origin=scaled=local → 런타임 오버라이드를 no-op 으로."""
    return tuple(local), tuple(local)


# ==========================================================================
# 3. 번들 처리
# ==========================================================================
def process_bundle(in_path, out_path, mode="rebase", edits=None, height_edits=None,
                   adds=None, eps=1e-3, packer="original", log=print, dry_run=False):
    """mode: 'rebase' | 'neutralize' | 'none'  — 불일치 항목 자동 수리 방식.
    edits: {(target_name, kind, bone): {'origin':(x,y,z)|None, 'scaled':(x,y,z)|None}}
           수동 편집(자동 수리보다 우선).
    height_edits: {target_name: float}  heightScale 덮어쓰기.
    adds: [{'target_name':str|None, 'kind':'pos'|'scale', 'bone':str,
            'origin':(x,y,z)|None, 'scaled':(x,y,z)|None}]  새 항목 추가.
          origin/scaled 가 None 이면 본의 현재 local 값으로 채운다(추가 시 no-op 시작)."""
    edits = edits or {}
    height_edits = height_edits or {}
    adds = adds or []
    env = UnityPy.load(str(in_path))
    objs = list(env.objects)
    uid = {o.path_id: o for o in objs}
    go = _go_name_map(env)
    name2pid = _bone_pid_map(env)

    def bone_local(pid, kind):
        o = uid.get(pid)
        if not o or o.type.name != "Transform":
            return None, None
        t = o.read_typetree()
        nm = go.get(t.get("m_GameObject", {}).get("m_PathID"))
        key = "m_LocalPosition" if kind == "pos" else "m_LocalScale"
        return nm, _v3(t[key])

    def local_of(bone, kind):
        pid = name2pid.get(bone)
        if pid is None:
            return None
        _, lv = bone_local(pid, kind)
        return lv

    n_repair = n_manual = n_height = n_add = 0
    comp_seen = set()
    for o in objs:
        if o.type.name != "MonoBehaviour":
            continue
        mb = o.read_typetree()
        if not _is_node_scaling(mb):
            continue
        tname = mb.get("targetName", "?")
        touched = False

        if tname in height_edits:
            mb["heightScale"] = float(height_edits[tname]); n_height += 1; touched = True
            log(f"  [{tname}] heightScale -> {height_edits[tname]}")

        for kind, listkey in (("pos", "positionValues"), ("scale", "scaleValues")):
            for ev in mb.get(listkey, []):
                bn, local = bone_local(ev["target"]["m_PathID"], kind)
                origin = _v3(ev["originValue"]); scaled = _v3(ev["scaledValue"])
                key = (tname, kind, bn)

                if key in edits:                              # 수동 편집 우선
                    e = edits[key]
                    if e.get("origin") is not None:
                        ev["originValue"] = _d3(e["origin"]); origin = tuple(e["origin"])
                    if e.get("scaled") is not None:
                        ev["scaledValue"] = _d3(e["scaled"]); scaled = tuple(e["scaled"])
                    n_manual += 1; touched = True
                    log(f"  [{tname}] {kind} {bn}: manual edit")
                    continue

                if mode == "none" or local is None:
                    continue
                if _dist(origin, local) > eps:                # 불일치 → 자동 수리
                    if mode == "neutralize":
                        no, ns = neutralize_values(local)
                    else:
                        no, ns = rebase_values(origin, scaled, local, kind)
                    ev["originValue"] = _d3(no); ev["scaledValue"] = _d3(ns)
                    n_repair += 1; touched = True
                    tag = "neutralize" if mode == "neutralize" else "re-anchor"
                    log(f"  [{tname}] {kind} {bn}: {tag} origin->{tuple(round(v,4) for v in no)}")

        # ---- add brand-new entries targeting other bones ----
        comp_seen.add(tname)
        for a in adds:
            at = a.get("target_name")
            if at not in (None, "*", tname):
                continue
            kind = a.get("kind", "scale")
            bone = a["bone"]
            pid = name2pid.get(bone)
            if pid is None:
                log(f"  [{tname}] add {kind} {bone}: bone not found — skipped")
                continue
            listkey = "positionValues" if kind == "pos" else "scaleValues"
            lst = mb.setdefault(listkey, [])
            existing = next((ev for ev in lst if ev["target"]["m_PathID"] == pid), None)
            local = local_of(bone, kind)
            origin = tuple(a["origin"]) if a.get("origin") is not None else (local or (0, 0, 0))
            scaled = tuple(a["scaled"]) if a.get("scaled") is not None else (local or (0, 0, 0))
            if existing is not None:                       # 이미 있으면 추가 대신 갱신
                existing["originValue"] = _d3(origin); existing["scaledValue"] = _d3(scaled)
                log(f"  [{tname}] add {kind} {bone}: already present -> updated")
            else:
                lst.append({"target": {"m_FileID": 0, "m_PathID": pid},
                            "originValue": _d3(origin), "scaledValue": _d3(scaled)})
                log(f"  [{tname}] add {kind} {bone}: new entry "
                    f"scaled={tuple(round(v,4) for v in scaled)}")
            n_add += 1; touched = True

        if touched and not dry_run:
            o.save_typetree(mb)

    # adds targeting a component name that wasn't found
    for a in adds:
        at = a.get("target_name")
        if at not in (None, "*") and at not in comp_seen:
            log(f"  [warn] add target component '{at}' not found in bundle — skipped")

    total = n_repair + n_manual + n_height + n_add
    if dry_run:
        log(f"  (preview) would change {total} item(s): {n_repair} repaired, "
            f"{n_manual} manual, {n_add} added, {n_height} heightScale")
        return total
    if total == 0:
        log("  no changes — healthy (nothing saved)")
        return 0
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    blob = env.file.save(packer=packer)
    with open(out_path, "wb") as f:
        f.write(blob)
    log(f"  saved: {out_path}  ({len(blob):,} bytes) — {n_repair} repaired, "
        f"{n_manual} manual, {n_add} added, {n_height} heightScale")
    return total


def process_folder(in_dir, out_dir, mode="rebase", suffix="_nodescalefix",
                   prefix="", eps=1e-3, packer="original", patterns=("*.unity",),
                   log=print, dry_run=False):
    in_dir, out_dir = Path(in_dir), Path(out_dir)
    files = []
    for pat in patterns:
        files += sorted(in_dir.glob(pat))
    files = [f for f in files if f.is_file()]
    if not files:
        log(f"no matching files in input folder: {in_dir}")
        return
    log(f"processing {len(files)} file(s)\n")
    for f in files:
        out_name = f"{prefix}{f.stem}{suffix}{f.suffix}"
        log(f"• {f.name} -> {out_name}")
        try:
            process_bundle(f, out_dir / out_name, mode=mode, eps=eps, packer=packer,
                           log=log, dry_run=dry_run)
        except Exception as e:
            log(f"  ! failed: {e}")
        log("")
    log("batch done.")


# ==========================================================================
# 4. CLI
# ==========================================================================
def _triple(v):
    n = [float(x) for x in v.split(",")]
    return tuple((n * 3)[:3]) if len(n) == 1 else tuple(n[:3])


def _parse_kv(spec, default_kind):
    """'bone;origin=..;scaled=..;kind=..;target=..' → (bone, kind, origin, scaled, target)."""
    parts = [p.strip() for p in spec.split(";")]
    bone = parts[0]
    kind, origin, scaled, target = default_kind, None, None, None
    for p in parts[1:]:
        if "=" not in p:
            continue
        k, v = p.split("=", 1); k = k.strip().lower()
        if k == "kind":
            kind = "scale" if v.strip().lower().startswith("s") else "pos"
        elif k in ("o", "origin"):
            origin = _triple(v)
        elif k in ("s", "scaled", "scale"):
            scaled = _triple(v)
        elif k in ("t", "target", "targetname"):
            target = v.strip()
    return bone, kind, origin, scaled, target


def _parse_set(spec):
    """'bone;origin=x,y,z;scaled=x,y,z;kind=pos'  → ((kind,bone), {origin,scaled})."""
    bone, kind, origin, scaled, _ = _parse_kv(spec, "pos")
    return (kind, bone), {"origin": origin, "scaled": scaled}


def _parse_add(spec):
    """'Bone;scaled=x,y,z;kind=scale[;origin=..][;target=..]' → add-dict.
    추가 시 기본 kind=scale(체형 보정). origin 미지정 시 본의 현재 local 로 채움."""
    bone, kind, origin, scaled, target = _parse_kv(spec, "scale")
    return {"target_name": target, "kind": kind, "bone": bone,
            "origin": origin, "scaled": scaled}


def run_cli(args):
    if args.list_bones:
        env = UnityPy.load(args.infile)
        for nm, pid, lp, ls in bone_catalog(env):
            print(f"  {nm:28s} localPos=({','.join(f'{v:.3f}' for v in lp)}) "
                  f"localScale=({','.join(f'{v:.3f}' for v in ls)})")
        return 0
    if args.list_entries:
        env = UnityPy.load(args.infile)
        comps, entries = scan_components(env)
        for o, mb, tname, hs in comps:
            print(f"\n[{tname}]  heightScale={round(hs,4)}")
        for e in entries:
            loc = "n/a" if e.local is None else ",".join(f"{v:.4f}" for v in e.local)
            print(f"  {e.kind:5s} {e.bone:22s} status={e.status():8s} "
                  f"origin=({','.join(f'{v:.4f}' for v in e.origin)}) "
                  f"scaled=({','.join(f'{v:.4f}' for v in e.scaled)}) local=({loc})")
        return 0

    edits = {}
    for spec in (args.set or []):
        (kind, bone), vals = _parse_set(spec)
        # targetName 은 처리 시점에 채워야 하므로 와일드카드로 둔다(아래 매칭).
        edits[("*", kind, bone)] = vals

    # ('*', ...) 키를 실제 targetName 으로 펼치려면 process_bundle 이 bone+kind 로
    # 매칭하도록 키를 (None) 처리. 간단히 처리하기 위해 edits 키의 target_name 을
    # 무시하는 래퍼를 쓴다.
    def expand(in_path):
        if not edits:
            return None
        env = UnityPy.load(str(in_path))
        _, entries = scan_components(env)
        out = {}
        for e in entries:
            k = ("*", e.kind, e.bone)
            if k in edits:
                out[(e.target_name, e.kind, e.bone)] = edits[k]
        return out

    adds = [_parse_add(s) for s in (args.add or [])]

    common = dict(mode=args.repair, eps=args.eps, packer=args.packer, dry_run=args.dry_run)
    if args.in_dir:
        if not args.out_dir:
            print("--in-dir requires --out-dir."); return 2
        if edits or adds:
            print("[note] --set/--add are ignored in folder/batch mode; use single-file --in/--out.")
        process_folder(args.in_dir, args.out_dir, suffix=args.suffix, prefix=args.prefix,
                       **{k: v for k, v in common.items()})
    else:
        if not args.infile or not args.outfile:
            print("--in and --out are required."); return 2
        process_bundle(args.infile, args.outfile, edits=expand(args.infile),
                       adds=adds, **common)
    return 0


def build_parser():
    p = argparse.ArgumentParser(
        prog="sifas_node_scaling",
        description="Edit/repair LiveCoreMemberNodeScaling (fixes ribbon/skirt that "
                    "teleport to the chest in-game while looking fine in a viewer).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("--gui", action="store_true", help="force GUI")
    p.add_argument("--menu", "--cli", dest="menu", action="store_true", help="force text menu")
    p.add_argument("--in", dest="infile", help="input bundle")
    p.add_argument("--out", dest="outfile", help="output bundle")
    p.add_argument("--in-dir", dest="in_dir", help="input folder (batch)")
    p.add_argument("--out-dir", dest="out_dir", help="output folder (batch)")
    p.add_argument("--prefix", default="", help="batch output filename prefix")
    p.add_argument("--suffix", default="_nodescalefix", help="batch output filename suffix")
    p.add_argument("--repair", default="rebase", choices=["rebase", "neutralize", "none"],
                   help="how to fix entries whose originValue drifted from the bone: "
                        "rebase keeps body shaping; neutralize makes the override a no-op")
    p.add_argument("--set", action="append",
                   help="'Bone;scaled=x,y,z;origin=x,y,z;kind=pos' edit an EXISTING entry (repeatable, single-file)")
    p.add_argument("--add", action="append",
                   help="'Bone;scaled=x,y,z;kind=scale[;target=ch..body]' ADD a new entry for "
                        "another bone (repeatable, single-file). kind defaults to scale; "
                        "origin defaults to the bone's current local value")
    p.add_argument("--list-bones", action="store_true",
                   help="list every bone name you can target with --add, then exit")
    p.add_argument("--eps", type=float, default=1e-3, help="tolerance (origin vs local)")
    p.add_argument("--packer", default="original",
                   choices=["original", "lz4", "lzma", "none"], help="save compression")
    p.add_argument("--list", dest="list_entries", action="store_true",
                   help="list NodeScaling entries then exit")
    p.add_argument("--dry-run", action="store_true", help="preview only (no save)")
    return p


# ==========================================================================
# 5. 텍스트 메뉴 (헤드리스)
# ==========================================================================
def _ask(prompt, default=None):
    s = input(f"{prompt}" + (f" [{default}]" if default is not None else "") + ": ").strip()
    return s if s else (default if default is not None else "")


def _ask_yn(prompt, default="y"):
    return _ask(prompt + " (y/n)", default).lower().startswith("y")


def run_menu():
    print("\n=== SIFAS NodeScaling Editor (text menu) ===")
    infile = _ask("Input bundle path")
    if not infile or not os.path.exists(infile):
        print("File not found."); return
    env = UnityPy.load(infile)
    comps, entries = scan_components(env)
    if not comps:
        print("No LiveCoreMemberNodeScaling component found."); return
    for o, mb, tname, hs in comps:
        print(f"\n[{tname}]  heightScale={round(hs,4)}")
    print("\nEntries:")
    bad = 0
    for e in entries:
        loc = "n/a" if e.local is None else ",".join(f"{v:.3f}" for v in e.local)
        mark = "" if e.status() == "ok" else "   <== " + e.status()
        if e.status() != "ok":
            bad += 1
        print(f"  {e.kind:5s} {e.bone:22s} origin=({','.join(f'{v:.3f}' for v in e.origin)}) "
              f"scaled=({','.join(f'{v:.3f}' for v in e.scaled)}) local=({loc}){mark}")
    print(f"\n{bad} inconsistent entr{'y' if bad == 1 else 'ies'} found.")
    mode = _ask("Repair mode (rebase/neutralize/none)", "rebase")

    adds = []
    if _ask_yn("\nAdd NodeScaling for other bones (body shaping)?", "n"):
        catalog = {nm for nm, *_ in bone_catalog(env)}
        print("(tip: run with --list-bones to see every bone name)")
        while True:
            bone = _ask("  Bone name (blank to finish)")
            if not bone:
                break
            if bone not in catalog:
                print(f"    '{bone}' not found — skipped"); continue
            kind = "scale" if _ask("  kind (scale/pos)", "scale").lower().startswith("s") else "pos"
            dv = "1,1,1" if kind == "scale" else "0,0,0"
            try:
                scaled = _triple(_ask(f"  scaledValue x,y,z", dv))
            except ValueError:
                print("    bad numbers — skipped"); continue
            adds.append({"target_name": None, "kind": kind, "bone": bone,
                         "origin": None, "scaled": scaled})
            print(f"    + {kind} {bone} scaled={scaled}")

    if bad == 0 and not adds and not _ask_yn("Bundle looks healthy. Save a copy anyway?", "n"):
        return
    default_out = str(Path(infile).with_name(Path(infile).stem + "_nodescalefix" + Path(infile).suffix))
    outfile = _ask("Output path", default_out)
    print("\nPreview:")
    process_bundle(infile, outfile, mode=mode, adds=adds, log=print, dry_run=True)
    if _ask_yn("\nSave?", "y"):
        process_bundle(infile, outfile, mode=mode, adds=adds, log=print)
    else:
        print("Cancelled.")


# ==========================================================================
# 6. Tkinter GUI  (sifas_mesh_baker 스타일)
# ==========================================================================
def run_gui():
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox

    state = {"env": None, "entries": [], "comps": [], "src": None,
             "catalog": [], "catalog_map": {}}
    rows = []   # [{entry, o_vars[3], s_vars[3], status_lbl}]
    height_rows = []  # [{target_name, var}]

    root = tk.Tk()
    root.title("SIFAS NodeScaling Editor")
    root.geometry("1180x840")
    root.minsize(1000, 620)
    PAD = 8
    main = ttk.Frame(root, padding=PAD)
    main.pack(fill="both", expand=True)

    # ---------- TOP: target ----------
    src = ttk.LabelFrame(main, text="Target", padding=PAD)
    src.pack(side="top", fill="x")
    mode_io = tk.StringVar(value="file")
    ttk.Radiobutton(src, text="Single file", variable=mode_io, value="file").grid(row=0, column=0, sticky="w")
    ttk.Radiobutton(src, text="Folder (batch)", variable=mode_io, value="dir").grid(row=0, column=1, sticky="w")
    in_var, out_var, suffix_var = tk.StringVar(), tk.StringVar(), tk.StringVar(value="_nodescalefix")
    _auto = {"val": ""}

    def suggest_out(*_):
        cur = out_var.get()
        if mode_io.get() == "file" and in_var.get() and (cur == "" or cur == _auto["val"]):
            base, ext = os.path.splitext(in_var.get())
            nv = base + suffix_var.get() + (ext or ".unity")
            _auto["val"] = nv; out_var.set(nv)
    in_var.trace_add("write", suggest_out)

    ttk.Label(src, text="Input").grid(row=1, column=0, sticky="e")
    e_in = ttk.Entry(src, textvariable=in_var, width=84)
    e_in.grid(row=1, column=1, columnspan=3, sticky="we", padx=4)
    ttk.Label(src, text="Output").grid(row=2, column=0, sticky="e")
    e_out = ttk.Entry(src, textvariable=out_var, width=84)
    e_out.grid(row=2, column=1, columnspan=3, sticky="we", padx=4)
    ttk.Label(src, text="Batch suffix").grid(row=3, column=0, sticky="e")
    ttk.Entry(src, textvariable=suffix_var, width=16).grid(row=3, column=1, sticky="w", padx=4)
    src.columnconfigure(1, weight=1)
    for e in (e_in, e_out):                     # 긴 경로의 끝(파일명)이 보이도록
        def _end(*_, w=e):
            w.after_idle(lambda: w.xview_moveto(1.0))
        (in_var if e is e_in else out_var).trace_add("write", _end)

    def browse_in():
        p = (filedialog.askopenfilename(title="Input bundle",
             filetypes=[("Unity bundle", "*.unity *.bundle *.ab"), ("All", "*.*")])
             if mode_io.get() == "file" else filedialog.askdirectory(title="Input folder"))
        if p:
            in_var.set(p)

    def browse_out():
        p = (filedialog.asksaveasfilename(title="Output bundle", defaultextension=".unity")
             if mode_io.get() == "file" else filedialog.askdirectory(title="Output folder"))
        if p:
            out_var.set(p)

    ttk.Button(src, text="Browse", command=browse_in).grid(row=1, column=4, padx=4)
    ttk.Button(src, text="Browse", command=browse_out).grid(row=2, column=4, padx=4)
    ttk.Button(src, text="Scan", command=lambda: scan()).grid(row=3, column=4, padx=4)

    # ---------- BOTTOM (pinned): run / log / options ----------
    run_btns = ttk.Frame(main)
    run_btns.pack(side="bottom", fill="x", pady=(PAD, 0))
    ttk.Button(run_btns, text="Preview", command=lambda: do_run(True)).pack(side="left")
    ttk.Button(run_btns, text="Apply + Save", command=lambda: do_run(False)).pack(side="left", padx=6)
    ttk.Label(run_btns, foreground="#666",
              text="ok = bone matches originValue · MISMATCH = will teleport in-game").pack(side="right")

    log_frame = ttk.LabelFrame(main, text="Log", padding=4)
    log_frame.pack(side="bottom", fill="x")
    log_text = tk.Text(log_frame, height=8, wrap="word")
    log_text.pack(side="left", fill="both", expand=True)
    lsb = ttk.Scrollbar(log_frame, command=log_text.yview); lsb.pack(side="right", fill="y")
    log_text.configure(yscrollcommand=lsb.set)

    opt = ttk.Frame(main)
    opt.pack(side="bottom", fill="x", pady=(PAD, 0))
    ttk.Label(opt, text="Auto-repair inconsistent:").pack(side="left")
    repair_label = tk.StringVar(value="Re-anchor (rebase · keep body shaping)")
    _REPAIR2KEY = {
        "Re-anchor (rebase · keep body shaping)": "rebase",
        "Neutralize (override = no-op)": "neutralize",
        "None (manual edits only)": "none",
    }
    ttk.Combobox(opt, textvariable=repair_label, width=34, state="readonly",
                 values=list(_REPAIR2KEY.keys())).pack(side="left", padx=(6, 0))
    ttk.Label(opt, text="Compression").pack(side="left", padx=(16, 4))
    packer_var = tk.StringVar(value="original")
    ttk.Combobox(opt, textvariable=packer_var, width=10,
                 values=["original", "lz4", "lzma", "none"], state="readonly").pack(side="left")

    # ---------- MIDDLE (expands): entries editor ----------
    mid = ttk.LabelFrame(main, text="NodeScaling entries  (edit originValue / scaledValue directly, "
                                    "or use the repair buttons)", padding=PAD)
    mid.pack(side="top", fill="both", expand=True, pady=PAD)

    bar = ttk.Frame(mid); bar.pack(fill="x")
    ttk.Button(bar, text="Re-anchor inconsistent", command=lambda: bulk("rebase")).pack(side="left")
    ttk.Button(bar, text="Neutralize inconsistent", command=lambda: bulk("neutralize")).pack(side="left", padx=6)
    ttk.Button(bar, text="Reset scaled = origin", command=lambda: bulk("reset")).pack(side="left")
    ttk.Button(bar, text="Revert to scanned", command=lambda: render_rows()).pack(side="left", padx=6)

    # add-entry bar: target another bone that has no NodeScaling entry yet
    addbar = ttk.Frame(mid); addbar.pack(fill="x", pady=(4, 2))
    ttk.Label(addbar, text="Add new part →  bone").pack(side="left")
    add_bone_var = tk.StringVar()
    add_bone_cb = ttk.Combobox(addbar, textvariable=add_bone_var, width=26, values=[])
    add_bone_cb.pack(side="left", padx=(4, 8))
    ttk.Label(addbar, text="kind").pack(side="left")
    add_kind_var = tk.StringVar(value="scale (body shape)")
    ttk.Combobox(addbar, textvariable=add_kind_var, width=18, state="readonly",
                 values=["scale (body shape)", "pos (offset)"]).pack(side="left", padx=(4, 8))
    ttk.Label(addbar, text="on").pack(side="left")
    add_comp_var = tk.StringVar()
    add_comp_cb = ttk.Combobox(addbar, textvariable=add_comp_var, width=22, state="readonly", values=[])
    add_comp_cb.pack(side="left", padx=(4, 8))
    ttk.Button(addbar, text="Add entry", command=lambda: add_new_entry()).pack(side="left")

    canvas = tk.Canvas(mid, highlightthickness=0)
    inner = ttk.Frame(canvas)
    vsb = ttk.Scrollbar(mid, orient="vertical", command=canvas.yview)
    hsb = ttk.Scrollbar(mid, orient="horizontal", command=canvas.xview)
    canvas.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
    canvas.pack(side="left", fill="both", expand=True)
    vsb.pack(side="right", fill="y")
    hsb.pack(side="bottom", fill="x")
    canvas.create_window((0, 0), window=inner, anchor="nw")
    inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

    COLW = [150, 44, 64, 64, 64, 64, 64, 64, 110, 80]
    for c, wd in enumerate(COLW):
        inner.columnconfigure(c, minsize=wd, weight=0)
    HEADERS = ["Bone (targetName)", "Kind",
               "origin X", "origin Y", "origin Z",
               "scaled X", "scaled Y", "scaled Z", "local (current)", "status"]

    def build_header():
        for c, h in enumerate(HEADERS):
            ttk.Label(inner, text=h, anchor="w").grid(row=0, column=c, sticky="w", padx=2, pady=(0, 3))

    def log(msg=""):
        log_text.insert("end", str(msg) + "\n"); log_text.see("end"); root.update_idletasks()

    def clear_rows():
        for r in rows:
            for w in r["widgets"]:
                w.destroy()
        rows.clear()
        for hr in height_rows:
            for w in hr["widgets"]:
                w.destroy()
        height_rows.clear()

    def make_entry_row(e, is_new=False):
        r = 1 + len(height_rows) + len(rows)
        wlist = []
        tag = "  (new)" if is_new else ""
        bn = ttk.Label(inner, text=f"{e.bone}  [{e.target_name}]{tag}")
        bn.grid(row=r, column=0, sticky="w", padx=2, pady=1); wlist.append(bn)
        kd = ttk.Label(inner, text=e.kind)
        kd.grid(row=r, column=1, sticky="w"); wlist.append(kd)
        ov = [tk.StringVar(value=f"{round(e.origin[k],6)}") for k in range(3)]
        sv = [tk.StringVar(value=f"{round(e.scaled[k],6)}") for k in range(3)]
        for k in range(3):
            w = ttk.Entry(inner, textvariable=ov[k], width=8)
            w.grid(row=r, column=2 + k, sticky="w", padx=1); wlist.append(w)
        for k in range(3):
            w = ttk.Entry(inner, textvariable=sv[k], width=8)
            w.grid(row=r, column=5 + k, sticky="w", padx=1); wlist.append(w)
        loc = "n/a" if e.local is None else ", ".join(f"{v:.3f}" for v in e.local)
        ll = ttk.Label(inner, text=loc, foreground="#555")
        ll.grid(row=r, column=8, sticky="w", padx=2); wlist.append(ll)
        init_status = "NEW" if is_new else e.status()
        st = tk.StringVar(value=init_status)
        sl = ttk.Label(inner, textvariable=st,
                       foreground=("#1763c0" if is_new else
                                   "#157f15" if init_status == "ok" else "#b00"))
        sl.grid(row=r, column=9, sticky="w", padx=2); wlist.append(sl)
        row = {"entry": e, "o": ov, "s": sv, "status": st, "lbl": sl,
               "widgets": wlist, "is_new": is_new}

        def _del(rw=row):
            for w in rw["widgets"]:
                w.destroy()
            if rw in rows:
                rows.remove(rw)
            canvas.configure(scrollregion=canvas.bbox("all"))

        if is_new:
            dl = ttk.Button(inner, text="✕", width=2, command=_del)
            dl.grid(row=r, column=10, padx=(2, 0)); wlist.append(dl)
        rows.append(row)
        canvas.configure(scrollregion=canvas.bbox("all"))
        return row

    def render_rows():
        clear_rows()
        for w in inner.winfo_children():
            w.destroy()
        build_header()
        # heightScale per component (editable)
        seen = set()
        for o, mb, tname, hs in state["comps"]:
            if tname in seen:
                continue
            seen.add(tname)
            r = 1 + len(height_rows)
            lbl = ttk.Label(inner, text=f"heightScale [{tname}]")
            lbl.grid(row=r, column=0, columnspan=2, sticky="w", padx=2, pady=1)
            hv = tk.StringVar(value=f"{round(hs,6)}")
            ent = ttk.Entry(inner, textvariable=hv, width=10)
            ent.grid(row=r, column=2, sticky="w", padx=2)
            height_rows.append({"target_name": tname, "var": hv, "widgets": [lbl, ent]})
        for e in state["entries"]:
            make_entry_row(e, is_new=False)
        canvas.configure(scrollregion=canvas.bbox("all"))

    def add_new_entry():
        if not state["comps"]:
            messagebox.showwarning("Add", "Scan a bundle first."); return
        bone = add_bone_var.get().strip()
        cat = state["catalog_map"].get(bone)
        if not cat:
            messagebox.showwarning("Add", "Pick a bone from the list."); return
        kind = "pos" if add_kind_var.get().startswith("pos") else "scale"
        tname = add_comp_var.get().strip() or state["comps"][0][2]
        if any(r.get("is_new") and r["entry"].bone == bone and r["entry"].kind == kind
               and r["entry"].target_name == tname for r in rows):
            log(f"[add] {kind} {bone} already queued."); return
        local = cat[1] if kind == "pos" else cat[2]
        e = Entry(0, tname, kind, -1, bone, local, local, local, False)
        make_entry_row(e, is_new=True)
        log(f"[add] queued new {kind} entry for '{bone}' on [{tname}] "
            f"(origin/scaled = current local {tuple(round(v,3) for v in local)}); "
            f"edit 'scaled' then Apply.")

    def _get3(vs, fallback):
        try:
            return tuple(float(v.get()) for v in vs)
        except ValueError:
            return tuple(fallback)

    def _refresh_status(row):
        e = row["entry"]
        if e.local is None:
            row["status"].set("MISSING"); return
        origin = _get3(row["o"], e.origin)
        ok = _dist(origin, e.local) <= 1e-3
        row["status"].set("ok" if ok else "MISMATCH")
        row["lbl"].configure(foreground="#157f15" if ok else "#b00")

    def bulk(kind):
        n = 0
        for row in rows:
            e = row["entry"]
            if e.local is None:
                continue
            origin = _get3(row["o"], e.origin); scaled = _get3(row["s"], e.scaled)
            if kind == "reset":
                for k in range(3):
                    row["s"][k].set(f"{round(origin[k],6)}")
                n += 1
                continue
            if _dist(origin, e.local) <= 1e-3:        # 일치 항목은 건드리지 않음
                continue
            if kind == "neutralize":
                no, ns = neutralize_values(e.local)
            else:
                no, ns = rebase_values(origin, scaled, e.local, e.kind)
            for k in range(3):
                row["o"][k].set(f"{round(no[k],6)}")
                row["s"][k].set(f"{round(ns[k],6)}")
            _refresh_status(row)
            n += 1
        log(f"{kind}: updated {n} row(s). Review, then 'Apply + Save'.")

    def scan():
        path = in_var.get().strip()
        if mode_io.get() == "dir":
            files = sorted(Path(path).glob("*.unity"))
            if not files:
                messagebox.showwarning("Scan", "No .unity files in the folder."); return
            path = str(files[0]); log(f"Scanning first file in folder: {Path(path).name}")
        if not path or not os.path.exists(path):
            messagebox.showwarning("Scan", "Check the input path."); return
        try:
            env = UnityPy.load(path)
            comps, entries = scan_components(env)
            catalog = bone_catalog(env)
            cat_map = {nm: (pid, lp, ls) for nm, pid, lp, ls in catalog}
            state.update(env=env, comps=comps, entries=entries, src=path,
                         catalog=catalog, catalog_map=cat_map)
            render_rows()
            # populate the add-entry pickers
            add_bone_cb.configure(values=[nm for nm, *_ in catalog])
            comp_names = list(dict.fromkeys(c[2] for c in comps))
            add_comp_cb.configure(values=comp_names)
            if comp_names and not add_comp_var.get():
                add_comp_var.set(comp_names[0])
            bad = sum(1 for e in entries if e.status() != "ok")
            log(f"Scan done: {len(comps)} component(s), {len(entries)} entr"
                f"{'y' if len(entries) == 1 else 'ies'}, {bad} inconsistent. "
                f"{len(catalog)} bones available to add.")
            if bad:
                log("  -> click 'Re-anchor inconsistent' (keeps body shaping) then 'Apply + Save'.")
        except Exception as e:
            messagebox.showerror("Scan failed", str(e))

    def collect_edits():
        edits, hedits, adds = {}, {}, []
        for row in rows:
            e = row["entry"]
            origin = _get3(row["o"], e.origin); scaled = _get3(row["s"], e.scaled)
            if row.get("is_new"):
                adds.append({"target_name": e.target_name, "kind": e.kind, "bone": e.bone,
                             "origin": origin, "scaled": scaled})
            elif _dist(origin, e.origin) > 1e-9 or _dist(scaled, e.scaled) > 1e-9:
                edits[(e.target_name, e.kind, e.bone)] = {"origin": origin, "scaled": scaled}
        for hr in height_rows:
            try:
                hedits[hr["target_name"]] = float(hr["var"].get())
            except ValueError:
                pass
        # heightScale: 변경된 것만
        for o, mb, tname, hs in state["comps"]:
            if tname in hedits and abs(hedits[tname] - hs) < 1e-9:
                hedits.pop(tname, None)
        return edits, hedits, adds

    def do_run(dry):
        inp, outp = in_var.get().strip(), out_var.get().strip()
        if not inp:
            messagebox.showwarning("Path", "Set the input path."); return
        mode = _REPAIR2KEY.get(repair_label.get(), "rebase")
        log("=" * 62)
        try:
            if mode_io.get() == "dir":
                if not outp:
                    messagebox.showwarning("Path", "Set the output folder."); return
                if rows:
                    log("[note] per-row manual edits apply to single-file mode only; "
                        "batch uses the auto-repair mode for every file.")
                process_folder(inp, outp, mode=mode, suffix=suffix_var.get(),
                               packer=packer_var.get(), log=log, dry_run=dry)
            else:
                if not outp:
                    outp = str(Path(inp).with_name(Path(inp).stem + suffix_var.get() + Path(inp).suffix))
                    out_var.set(outp)
                edits, hedits, adds = collect_edits()
                log(f"• {Path(inp).name} -> {Path(outp).name}")
                process_bundle(inp, outp, mode=mode, edits=edits, height_edits=hedits,
                               adds=adds, packer=packer_var.get(), log=log, dry_run=dry)
            log("Preview done." if dry else "Done.")
        except Exception as e:
            log(f"! error: {e}"); messagebox.showerror("Failed", str(e))

    build_header()
    log("Select an input bundle -> 'Scan' -> review entries (MISMATCH = teleports in-game) "
        "-> 'Re-anchor inconsistent' -> 'Apply + Save'.")
    root.mainloop()


# ==========================================================================
# 7. 진입점
# ==========================================================================
def has_display_gui():
    if "com.termux" in os.environ.get("PREFIX", ""):
        return False
    if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
        return False
    try:
        import tkinter  # noqa
        return True
    except Exception:
        return False


def main():
    args = build_parser().parse_args()
    if args.menu:
        return run_menu()
    if args.gui:
        return run_gui()
    if (args.list_entries or args.list_bones or args.set or args.add
            or args.in_dir or (args.infile and args.outfile)):
        return run_cli(args)
    return run_gui() if has_display_gui() else run_menu()


if __name__ == "__main__":
    sys.exit(main() or 0)
