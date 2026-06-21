#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""facial_inject 핵심 로직 테스트 (UnityPy 불필요)."""
import importlib.util
import tempfile
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "facial_inject", str(Path(__file__).with_name("facial_inject.py")))
fi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fi)


def test_tables_match_confirmed_indices():
    # 실제 so2002 번들에서 확인한 값
    assert fi.EYE["Close"] == 1 and fi.EYE["WideOpen"] == 4
    assert fi.EYE["WinkR"] == 12 and fi.EYE["WinkL"] == 13
    assert fi.GAZE["Camera"] == 21 and fi.GAZE["Audience"] == 22
    assert fi.GAZE["Left"] == 33 and fi.GAZE["Right"] == 34
    assert "Ppo" in fi.CHEEK


def test_parse_script_ok():
    txt = """# comment
    eye  0.0 2.0 Close 1.0
    gaze 1.97 4.3 Camera
    cheek 20.0 0.8 Ppo
    """
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write(txt); p = f.name
    ents = fi.parse_script(Path(p))
    assert len(ents) == 3
    assert ents[0].track == "eye" and ents[0].name == "Close" and ents[0].weight == 1.0
    assert ents[1].track == "gaze" and ents[1].weight == 1.0   # default weight
    assert ents[2].track == "cheek" and ents[2].name == "Ppo"


def test_parse_script_rejects_unknown():
    for bad in ["eye 0 1 Nope", "wat 0 1 Close", "gaze 0 1 Sideways"]:
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            f.write(bad); p = f.name
        try:
            fi.parse_script(Path(p))
            assert False, f"should reject: {bad}"
        except ValueError:
            pass


def test_auto_blink_reasonable():
    blinks = fi.auto_blink(duration=60.0, period=3.5, seed=1)
    assert all(b.track == "eye" and b.name == "Close" for b in blinks)
    assert all(0 < b.dur < 0.4 for b in blinks)              # short blinks
    ts = [b.start for b in blinks]
    assert ts == sorted(ts) and ts[-1] < 60.0                # in order, in range
    gaps = [b - a for a, b in zip(ts, ts[1:])]
    assert all(1.5 < g < 6.0 for g in gaps)                  # natural spacing


ALL = [v for k, v in sorted(globals().items()) if k.startswith("test_")]


def main():
    import traceback
    ok = 0
    for fn in ALL:
        try:
            fn(); ok += 1; print(f"[pass] {fn.__name__}")
        except Exception:
            print(f"[FAIL] {fn.__name__}"); traceback.print_exc()
    print(f"\n{ok}/{len(ALL)} passed")
    return 0 if ok == len(ALL) else 1


if __name__ == "__main__":
    raise SystemExit(main())
