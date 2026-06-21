#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sifas_timeline_inject 핵심 로직 테스트 (UnityPy / tkinter 불필요)."""
import importlib.util
import math
import random
import tempfile
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "sti", str(Path(__file__).with_name("sifas_timeline_inject.py")))
sti = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sti)


# ---- 입 (립싱크) ---- #
OLD_WHITELIST = {  # 기존 도구의 화이트리스트 (비교용)
    "ada": "A", "ama": "A", "aa": "A", "iri": "I", "isi": "I", "ii": "I",
    "uyu": "U", "uku": "U", "uu": "U", "ebe": "E", "ere": "E", "ee": "E",
    "odo": "O", "oo": "O", "nn": "N", "": "A",
}


def test_lip_basic_vowels():
    for code, shp in [("ada", "A"), ("isi", "I"), ("usu", "U"),
                      ("ete", "E"), ("oto", "O"), ("nn", "N"), ("n", "N")]:
        assert sti.reduce_phoneme(code) == shp, code


def test_lip_last_vowel_and_silence():
    assert sti.reduce_phoneme("oyo") == "O"
    assert sti.reduce_phoneme("usy") == "U"
    assert sti.reduce_phoneme("") is None
    assert sti.reduce_phoneme("xyz") is None


def test_lip_fixes_whitelist_misses():
    for code in ["oto", "usu", "ete", "oyo", "eme", "imi", "ono", "ubu"]:
        old = OLD_WHITELIST.get(code, "A")
        new = sti.reduce_phoneme(code)
        assert new is not None and new != "A" and new != old, code


def test_lip_index_table():
    for s in ("A", "I", "U", "E", "O", "N"):
        assert s in sti.SHAPE_INDEX


# ---- 표정 ---- #
def test_face_tables():
    assert sti.EYE["Close"] == 1 and sti.EYE["WinkR"] == 12 and sti.EYE["WinkL"] == 13
    assert sti.GAZE["Camera"] == 21 and sti.GAZE["Audience"] == 22 and sti.GAZE["Right"] == 34
    assert "Ppo" in sti.CHEEK


def test_face_parse_and_reject():
    txt = "eye 0 2 Close 1.0\ngaze 1.97 4.3 Camera\ncheek 20 0.8 Ppo\n# c\n"
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write(txt); p = f.name
    ents = sti.parse_script(Path(p))
    assert len(ents) == 3 and ents[1].weight == 1.0 and ents[2].name == "Ppo"
    for bad in ["eye 0 1 Nope", "wat 0 1 Close", "gaze 0 1 Sideways"]:
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            f.write(bad); q = f.name
        try:
            sti.parse_script(Path(q)); assert False, bad
        except ValueError:
            pass


def test_face_auto_blink():
    bl = sti.auto_blink(duration=60.0, seed=1)
    assert all(b.track == "eye" and b.name == "Close" and 0 < b.dur < 0.4 for b in bl)
    ts = [b.start for b in bl]
    assert ts == sorted(ts) and ts[-1] < 60.0


# ---- 카메라 ---- #
def _e2q(ex, ey, ez):
    rx, ry, rz = math.radians(ex) / 2, math.radians(ey) / 2, math.radians(ez) / 2
    qx = (math.sin(rx), 0, 0, math.cos(rx)); qy = (0, math.sin(ry), 0, math.cos(ry))
    qz = (0, 0, math.sin(rz), math.cos(rz))

    def qm(a, b):
        ax, ay, az, aw = a; bx, by, bz, bw = b
        return (aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
                aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz)
    return qm(qm(qy, qx), qz)


def test_cam_euler_roundtrip():
    rng = random.Random(0); worst = 0.0
    for _ in range(20000):
        e = (rng.uniform(-179, 179), rng.uniform(-179, 179), rng.uniform(-179, 179))
        q = _e2q(*e); q2 = _e2q(*sti.quat_to_unity_euler(q))
        worst = max(worst, min(sum((a - b) ** 2 for a, b in zip(q, q2)),
                               sum((a + b) ** 2 for a, b in zip(q, q2))))
    assert worst < 1e-5, worst


def test_cam_sample_array_and_zflip():
    fr = [{"t": i / 60.0, "pos": [float(i), 0.0, 2.0 * i],
           "rot": [0, 0, 0, 1], "fov": 30.0 + i} for i in range(3)]
    s = sti.resample_60(fr)
    assert len(s) == 3
    arr = sti.build_sample_array(s, z_flip=False)
    assert len(arr) == 3 * 7 and abs(arr[7 * 2 + 2] - 4.0) < 1e-6 and abs(arr[6] - 30.0) < 1e-6
    arrf = sti.build_sample_array(s, z_flip=True)
    assert abs(arrf[7 * 2 + 2] + 4.0) < 1e-6


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
