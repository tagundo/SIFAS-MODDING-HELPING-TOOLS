"""@UTF and AFS2 writers on synthetic tables.

Set SIFAS_TEST_ACB to a private local stock music cue sheet for the optional
byte-identity check.
"""
import math
import os
from pathlib import Path
import struct
import unittest

from webtools.core import cri_acb_write as acbw
from webtools.core import cri_audio_decode as cri
from webtools.core import cri_hca_encode as enc
from webtools.core.cri_acb_write import CONSTANT, PER_ROW, ZERO, UtfColumn, UtfTable


def table(name, columns, rows, align=0):
    return acbw.write_utf(UtfTable(name, 1, [UtfColumn(n, kind, PER_ROW) for n, kind in columns], rows, align))


class UtfTests(unittest.TestCase):
    def sample_table(self, align=0):
        values = {0: 200, 1: -100, 2: 60000, 3: -30000, 4: 4000000000, 5: -2000000000, 6: 2 ** 63 + 5,
                  7: -(2 ** 62), 8: 1.5, 9: 1 / 3, 10: "문자열 text", 11: b"\x01\x02\x03"}
        columns = []
        for kind, value in values.items():
            columns.append(UtfColumn(f"zero{kind}", kind, ZERO))
            columns.append(UtfColumn(f"const{kind}", kind, CONSTANT, value))
            columns.append(UtfColumn(f"row{kind}", kind, PER_ROW))
        rows = []
        for index in range(3):
            row = {}
            for kind, value in values.items():
                if kind == 10:
                    row[f"row{kind}"] = f"{value} {index}" if index != 1 else ""
                elif kind == 11:
                    row[f"row{kind}"] = value * (index + 1) if index != 1 else b""
                elif kind in (8, 9):
                    row[f"row{kind}"] = value * (index + 1)
                else:
                    row[f"row{kind}"] = value - index if value > 0 else value + index
            rows.append(row)
        return UtfTable("Sample", 1, columns, rows, align)

    def test_every_column_type_and_storage_round_trips(self):
        for align in (0, 32):
            with self.subTest(align=align):
                original = self.sample_table(align)
                raw = acbw.write_utf(original)
                self.assertEqual(len(raw) % 4, 0)
                parsed = acbw.read_utf(raw)
                self.assertEqual(parsed.name, "Sample")
                self.assertEqual([(c.name, c.kind, c.storage) for c in parsed.columns],
                                 [(c.name, c.kind, c.storage) for c in original.columns])
                self.assertEqual(parsed.align, align)
                self.assertEqual(acbw.write_utf(parsed), raw)
                repo = cri.utf_rows(raw)
                self.assertEqual(repo["name"], "Sample")
                for index, row in enumerate(repo["rows"]):
                    for column in original.columns:
                        expected = original.value(index, column.name)
                        if column.kind == 8:
                            expected = struct.unpack(">f", struct.pack(">f", expected))[0]
                        self.assertEqual(row[column.name], expected, (index, column.name))
                        self.assertEqual(parsed.value(index, column.name), expected)

    def test_root_layout_aligns_blobs_to_32_bytes(self):
        raw = acbw.write_utf(self.sample_table(32))
        _, size, _, _, strings_at, data_at, *_ = struct.unpack_from(">4sIHHIIIHHI", raw)
        self.assertEqual((data_at + 8) % 32, 0)
        self.assertEqual(len(raw) % 32, 0)
        parsed = acbw.read_utf(raw)
        offsets = []
        position = 32 + sum(5 + (acbw._WIDTHS[c.kind] if c.storage == CONSTANT else 0) for c in parsed.columns)
        for _ in parsed.rows:
            for column in parsed.columns:
                if column.storage == PER_ROW:
                    if column.kind == 11:
                        start, length = struct.unpack_from(">II", raw, position)
                        if length:
                            offsets.append(start)
                        else:
                            self.assertEqual(start, 0)
                    position += acbw._WIDTHS[column.kind]
        self.assertTrue(offsets and all(offset % 32 == 0 for offset in offsets))

    def test_string_pool_order_has_no_sharing(self):
        raw = table("Names", [("A", 10), ("B", 10)], [{"A": "", "B": ""}, {"A": "x", "B": "x"}])
        _, _, _, _, strings_at, data_at, *_ = struct.unpack_from(">4sIHHIIIHHI", raw)
        pool = raw[strings_at + 8:data_at + 8]
        self.assertEqual(pool, b"Names\0A\0B\0\0\0x\0x\0")

    def test_set_values_keeps_storage_flags_when_possible(self):
        parsed = acbw.read_utf(acbw.write_utf(self.sample_table()))
        parsed.set_values("const4", [7, 7, 7])
        self.assertEqual((parsed.column("const4").storage, parsed.column("const4").value), (CONSTANT, 7))
        parsed.set_values("zero2", [0, 0, 0])
        self.assertEqual(parsed.column("zero2").storage, ZERO)
        parsed.set_values("zero2", [5, 5, 5])
        self.assertEqual((parsed.column("zero2").storage, parsed.column("zero2").value), (CONSTANT, 5))
        parsed.set_values("const10", ["a", "b", "a"])
        self.assertEqual(parsed.column("const10").storage, PER_ROW)
        parsed.set(1, "row4", 9)
        self.assertEqual([parsed.value(i, "row4") for i in range(3)], [4000000000, 9, 3999999998])
        again = acbw.read_utf(acbw.write_utf(parsed))
        self.assertEqual([again.value(i, "const10") for i in range(3)], ["a", "b", "a"])
        for name, value in (("row0", 256), ("row1", -129), ("row10", 5), ("row11", "x"), ("row8", math.inf),
                            ("row2", True)):
            with self.subTest(name), self.assertRaises(ValueError):
                parsed.set(0, name, value)

    def test_rejects_corrupt_tables(self):
        raw = acbw.write_utf(self.sample_table())
        broken = []
        for at, value in ((4, 0xFFFFFFFF), (12, 0xFFFFFFFF), (16, 0xFFFFFFFF), (28, 0xFFFFFFFF)):
            corrupt = bytearray(raw)
            struct.pack_into(">I", corrupt, at, value)
            broken.append(bytes(corrupt))
        bad_storage = bytearray(raw)
        bad_storage[32] = 0x70
        broken += [bytes(bad_storage), b"", b"@UTF", raw[:31], b"XUTF" + raw[4:]]
        for corrupt in broken:
            with self.assertRaises(enc.AudioEncodeError):
                acbw.read_utf(corrupt)


class Afs2Tests(unittest.TestCase):
    def test_stock_layout_and_parsing(self):
        bank = acbw.write_afs2([(0, b"first entry"), (7, b"second")], alignment=32, subkey=0x1234)
        self.assertEqual(bank[:8], b"AFS2\x02\x04\x02\x00")
        count, alignment, subkey = struct.unpack_from("<IHH", bank, 8)
        self.assertEqual((count, alignment, subkey), (2, 32, 0x1234))
        header = acbw.afs2_header_size(2)
        self.assertEqual(header, 16 + 4 + 12)
        offsets = struct.unpack_from("<III", bank, 20)
        self.assertEqual(offsets[0], header)
        self.assertEqual(offsets[1], 32 + len(b"first entry"))
        self.assertEqual(offsets[2], len(bank))
        self.assertEqual(cri.awb_entries(bank), [{"id": 0, "start": 32, "end": 43, "subkey": 0x1234},
                                                 {"id": 7, "start": 64, "end": 70, "subkey": 0x1234}])
        parsed = acbw.read_afs2(bank)
        self.assertEqual(parsed["entries"], [(0, b"first entry"), (7, b"second")])
        rebuilt = acbw.write_afs2(parsed["entries"], version=parsed["version"], offset_size=parsed["offsetSize"],
                                  id_size=parsed["idSize"], alignment=parsed["alignment"], subkey=parsed["subkey"])
        self.assertEqual(rebuilt, bank)
        single = acbw.write_afs2([(0, b"x" * 100)])
        self.assertEqual(acbw.afs2_header_size(1), 26)
        self.assertEqual(struct.unpack_from("<II", single, 18), (26, 132))
        for entries, options in (([], {}), ([(0, b"a"), (0, b"b")], {}), ([(0, b"")], {}), ([(70000, b"a")], {}),
                                 ([(0, b"a")], {"offset_size": 3}), ([(0, b"a")], {"alignment": 0})):
            with self.assertRaises(ValueError):
                acbw.write_afs2(entries, **options)


@unittest.skipUnless(os.environ.get("SIFAS_TEST_ACB"), "Set a private local music ACB path for the stock layout check")
class PrivateStockLayoutTests(unittest.TestCase):
    def test_stock_cue_sheet_round_trips_byte_identically(self):
        acb = Path(os.environ["SIFAS_TEST_ACB"]).read_bytes()
        size = struct.unpack_from(">I", acb, 4)[0] + 8
        self.assertEqual(acbw.write_utf(acbw.read_utf(acb)), acb[:size])


if __name__ == "__main__":
    unittest.main()
