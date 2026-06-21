#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""smart_lipsync 핵심 로직 테스트 (UnityPy 불필요).

규칙 기반 음소→모음 매퍼가 (a) 실제 SIFAC 음소 코드를 올바른 입모양으로 환원하고
(b) 기존 화이트리스트가 조용히 "A"로 떨구던 코드들을 교정하는지 확인합니다.
"""
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "smart_lipsync", str(Path(__file__).with_name("smart_lipsync.py")))
sl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sl)

# 기존 도구(3_import_to_mouth)의 화이트리스트 — 비교용
OLD_WHITELIST = {
    "ada": "A", "awa": "A", "ama": "A", "ara": "A", "aya": "A", "aa": "A",
    "iri": "I", "ibi": "I", "ihi": "I", "ini": "I", "isi": "I", "ii": "I",
    "uyu": "U", "ugu": "U", "uhu": "U", "uku": "U", "uru": "U", "uu": "U",
    "ebe": "E", "ede": "E", "ehe": "E", "eke": "E", "ese": "E", "ee": "E", "ere": "E",
    "odo": "O", "owo": "O", "obo": "O", "ogo": "O", "oko": "O", "oo": "O", "oso": "O",
    "nn": "N", "": "A",
}


def test_basic_vowels():
    assert sl.reduce_phoneme("ada") == "A"
    assert sl.reduce_phoneme("isi") == "I"
    assert sl.reduce_phoneme("usu") == "U"
    assert sl.reduce_phoneme("ete") == "E"
    assert sl.reduce_phoneme("oto") == "O"
    assert sl.reduce_phoneme("nn") == "N"
    assert sl.reduce_phoneme("n") == "N"


def test_silence_and_unknown():
    assert sl.reduce_phoneme("") is None
    assert sl.reduce_phoneme("   ") is None
    # 자음만 있는(모음 없는) 코드는 무음 취급
    assert sl.reduce_phoneme("xyz") is None


def test_last_vowel_rule():
    # 마지막 모음이 입모양 — 들어오는 모음이 달라도 목표 모음으로
    assert sl.reduce_phoneme("oyo") == "O"
    assert sl.reduce_phoneme("eme") == "E"
    assert sl.reduce_phoneme("imi") == "I"
    assert sl.reduce_phoneme("ubu") == "U"
    assert sl.reduce_phoneme("usy") == "U"   # っ/장음 변형도 마지막 모음 기준


def test_fixes_whitelist_misses():
    # 기존 화이트리스트가 "A"로 떨구던 실제 코드들이 교정되는지
    misfires = ["oto", "usu", "ete", "oyo", "eme", "imi", "iki", "ono",
                "umu", "uzu", "izi", "ozy", "ege", "omo", "iti", "ubu"]
    fixed = 0
    for code in misfires:
        old = OLD_WHITELIST.get(code, "A")          # 미지 -> "A"
        new = sl.reduce_phoneme(code)
        assert new is not None and new != "A", code  # 전부 A가 아니어야
        if old != new:
            fixed += 1
    assert fixed == len(misfires)                    # 전부 교정


def test_index_table_complete():
    # 규칙이 낼 수 있는 모든 입모양이 SIFAS index 테이블에 있어야
    for shape in ("A", "I", "U", "E", "O", "N"):
        assert shape in sl.SHAPE_INDEX


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    ok = 0
    for fn in fns:
        try:
            fn(); ok += 1; print(f"[pass] {fn.__name__}")
        except Exception:
            print(f"[FAIL] {fn.__name__}"); traceback.print_exc()
    print(f"\n{ok}/{len(fns)} passed")
