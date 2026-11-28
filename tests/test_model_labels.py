"""Readable model names: member number, member and costume from the game's
dictionaries; identities (cache names, receipts) stay codes."""
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import zipfile

from webtools.core import model_labels as labels
from webtools.core import viewer_mod_flow as flow


OFFICIAL, INSTALLED, OLDER, UNNAMED, KEY_ONLY, RINA, COPY = 100041001, 227912766, 133542688, 555, 556, 302092002, 425995440
KOREAN_ONLY, OTHER_KEY = 557, 558
MEMBERS = {4: ("Umi Sonoda", "소노다 우미", "園田 海未"), 101: ("Chika Takami", "타카미 치카", "高海 千歌"),
           209: ("Rina Tennoji", "텐노지 리나", "天王寺 璃奈"), 211: ("Mia Taylor", "미아 테일러", "ミア・テイラー")}
# (en, ko, zh, ja) dictionary rows per suit; None is no row.
SUITS = {
    OFFICIAL: (4, ("Otonokizaka High Uniform (Winter)", "오토노키자카 고교 교복(동복)", "音乃木坂冬季制服", "音ノ木坂学院制服（冬服）")),
    # A Mod this feature named: every name already starts with the number and member.
    INSTALLED: (4, ("004 Umi Sonoda · Otonokizaka High Uniform (Winter) · Outlines",
                    "004 소노다 우미 · 오토노키자카 고교 교복(동복) · 외곽선",
                    "004 Umi Sonoda · Otonokizaka High Uniform (Winter) · Outlines",
                    "004 園田 海未 · 音ノ木坂学院制服（冬服） · 輪郭線")),
    # An older Mod: one English-only name; its other rows are empty.
    OLDER: (4, ("Otonokizaka High Uniform (Winter) · 외곽선", "", "", "")),
    UNNAMED: (4, (None, None, None, None)),
    KEY_ONLY: (4, ("k.suit_name_556", "suit:556", None, None)),
    # A Mod named only in Korean; a row holding some other raw key.
    KOREAN_ONLY: (4, ("", "한국어 이름", None, None)),
    OTHER_KEY: (4, ("k.suit_name_999", None, None, None)),
    RINA: (209, ("Rina outfit", "리나 의상", "璃奈衣装", "璃奈の衣装")),
}
# A second copy of the same added Mod.
SUITS[COPY] = SUITS[INSTALLED]


def build_root(root):
    """Tiny GL/JP masterdata and dictionaries with the game's own name keys."""
    for region, languages in (("gl", ("en", "ko", "zh")), ("jp", ("ja",))):
        directory = root / "assets/db" / region
        directory.mkdir(parents=True)
        with sqlite3.connect(directory / "masterdata.db") as db:
            db.execute("CREATE TABLE m_member(id INTEGER PRIMARY KEY, name TEXT)")
            db.execute("CREATE TABLE m_suit(id INTEGER PRIMARY KEY, member_m_id INTEGER, name TEXT, model_asset_path TEXT, display_order INTEGER)")
            db.execute("CREATE TABLE m_suit_view(suit_master_id INTEGER, view_status INTEGER, model_asset_path TEXT)")
            db.executemany("INSERT INTO m_member VALUES(?,?)", [(owner, f"k.m_dic_member_name_{owner}") for owner in MEMBERS])
            db.executemany("INSERT INTO m_suit VALUES(?,?,?,?,?)",
                           [(suit, owner, f"k.suit_name_{suit}", "x", order) for order, (suit, (owner, _)) in enumerate(SUITS.items())])
            db.execute("INSERT INTO m_suit_view VALUES(?,2,'y')", (RINA,))
        for language in languages:
            column = ("en", "ko", "zh", "ja").index(language)
            with sqlite3.connect(directory / f"dictionary_{language}_k.db") as db:
                db.execute("CREATE TABLE m_dictionary(id TEXT PRIMARY KEY, message TEXT)")
                for owner, names in MEMBERS.items():
                    name = names[0] if language in ("en", "zh") else names[1 if language == "ko" else 2]
                    db.execute("INSERT INTO m_dictionary VALUES(?,?)", (f"m_dic_member_name_{owner}", name))
                for suit, (_, names) in SUITS.items():
                    if names[column] is not None:
                        db.execute("INSERT INTO m_dictionary VALUES(?,?)", (f"suit_name_{suit}", names[column]))


def add_asset_catalog(root, suit=OFFICIAL):
    """The Android asset catalog rows game_models.validate_selection checks."""
    for region in ("gl", "jp"):
        with sqlite3.connect(root / "assets/db" / region / "masterdata.db") as db:
            db.execute("CREATE TABLE IF NOT EXISTS m_suit_attach(suit_master_id INTEGER, original_suit_master_id INTEGER, attach_key TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS m_suit_custom3d(suit_master_id INTEGER, skirtsafe_disable INTEGER)")
        with sqlite3.connect(root / "assets/db" / region / "asset_a_en.db") as db:
            db.executescript("CREATE TABLE member_model(asset_path TEXT, pack_name TEXT, head INTEGER, size INTEGER, key1 INTEGER, key2 INTEGER);"
                             "CREATE TABLE member_model_dependency(asset_path TEXT, dependency TEXT);"
                             "CREATE TABLE m_asset_package_mapping(package_key TEXT, pack_name TEXT, file_size INTEGER, metapack_name TEXT, metapack_offset INTEGER);")
            db.execute("INSERT INTO member_model VALUES('x','labelpack',0,64,7,11)")
            db.execute("INSERT INTO m_asset_package_mapping VALUES(?,'labelpack',64,NULL,0)", (f"suit:{suit}",))


def selection(root, suit=OFFICIAL):
    from webtools.core import game_models
    return game_models.validate_selection(root, {"region": "gl", "suit": f"suit:{suit}", "variant": "primary", "download": False}, "en")


def record(suit, variant="primary", region="gl"):
    return {"region": region, "suit_id": suit, "variant": variant, "owner": SUITS[suit][0]}


class TitledTests(unittest.TestCase):
    def test_number_member_and_name(self):
        self.assertEqual(labels.member_number(4), "004")
        self.assertEqual(labels.member_number(101), "101")
        self.assertEqual(labels.member_number(209), "209")
        for owner in (None, 0, 1000, True, "4"):
            self.assertIsNone(labels.member_number(owner))
        self.assertEqual(labels.titled(4, "소노다 우미", "의상"), "004 소노다 우미 · 의상")
        self.assertEqual(labels.titled(101, "高海 千歌", ""), "101 高海 千歌")

    def test_a_name_that_starts_with_the_number_or_member_is_not_given_them_twice(self):
        self.assertEqual(labels.titled(4, "소노다 우미", "004 소노다 우미 · 의상 · 외곽선"), "004 소노다 우미 · 의상 · 외곽선")
        self.assertEqual(labels.titled(4, "소노다 우미", "004_custom"), "004_custom")
        # Another language's member name (a Mod named in English) gets only the number.
        self.assertEqual(labels.titled(4, "소노다 우미", "Umi Sonoda — Winter", ("Umi Sonoda",)), "004 Umi Sonoda — Winter")
        # A number that merely starts the same way, or a longer word, is not the member.
        self.assertEqual(labels.titled(4, "소노다 우미", "0042 Winter"), "004 소노다 우미 · 0042 Winter")
        self.assertEqual(labels.titled(4, "Umi", "Umino Winter"), "004 Umi · Umino Winter")
        # Without a known member nothing is invented.
        self.assertEqual(labels.titled(None, None, "Winter"), "Winter")
        self.assertEqual(labels.titled(4, None, "Winter"), "Winter")

    def test_untitled_takes_back_only_what_titled_put_first(self):
        aliases = ("Umi Sonoda", "소노다 우미")
        for text in ("의상 · 외곽선", "", "Umi Sonoda — Winter", "0042 Winter", "004_custom", "Umino Winter"):
            with self.subTest(text=text):
                titled = labels.titled(4, "소노다 우미", text, aliases)
                self.assertEqual(labels.titled(4, "소노다 우미", labels.untitled(4, "소노다 우미", titled, aliases), aliases), titled)
        self.assertEqual(labels.untitled(4, "소노다 우미", "004 소노다 우미 · 의상 · 외곽선", aliases), "의상 · 외곽선")
        self.assertEqual(labels.untitled(4, "소노다 우미", "004 Umi Sonoda · Knit", aliases), "Knit")
        self.assertEqual(labels.untitled(4, "소노다 우미", "004 소노다 우미", aliases), "")
        self.assertEqual(labels.untitled(4, "소노다 우미", "004 Umi Sonoda — Winter", aliases), "Umi Sonoda — Winter")
        # Another member's number, a number without its member, or no member: unchanged.
        for text in ("101 타카미 치카 · 의상", "004 의상", "004_custom", "의상"):
            self.assertEqual(labels.untitled(4, "소노다 우미", text, aliases), text)
        self.assertEqual(labels.untitled(None, None, "004 소노다 우미 · 의상"), "004 소노다 우미 · 의상")


class RecordLabelTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        build_root(self.root)

    def test_official_costume_reads_number_member_and_costume_in_each_language(self):
        parts = labels.record_label(self.root, record(OFFICIAL))
        self.assertEqual(parts["label"], {"en": "004 Umi Sonoda · Otonokizaka High Uniform (Winter)",
                                          "ko": "004 소노다 우미 · 오토노키자카 고교 교복(동복)",
                                          "ja": "004 園田 海未 · 音ノ木坂学院制服（冬服）"})
        self.assertEqual(parts["nameBase"], parts["label"])
        self.assertEqual(parts["costume"]["ko"], "오토노키자카 고교 교복(동복)")
        self.assertEqual((parts["region"], parts["suitId"], parts["variant"], parts["owner"]), ("gl", OFFICIAL, "primary", 4))
        # A JP record finds the same names; its owner comes from m_suit when missing.
        jp = labels.record_label(self.root, {"region": "jp", "suit_id": OFFICIAL, "variant": "primary"})
        self.assertEqual(jp["label"], parts["label"])
        self.assertEqual(jp["owner"], 4)

    def test_installed_mod_name_is_used_as_installed(self):
        parts = labels.record_label(self.root, record(INSTALLED))
        self.assertEqual(parts["label"]["ko"], "004 소노다 우미 · 오토노키자카 고교 교복(동복) · 외곽선")
        self.assertEqual(parts["label"]["ja"], "004 園田 海未 · 音ノ木坂学院制服（冬服） · 輪郭線")
        self.assertEqual(parts["nameBase"]["en"], "004 Umi Sonoda · Otonokizaka High Uniform (Winter) · Outlines")

    def test_empty_rows_use_another_language_and_keys_never_show(self):
        older = labels.record_label(self.root, record(OLDER))
        self.assertEqual(older["label"], {code: "004 " + name + " · Otonokizaka High Uniform (Winter) · 외곽선"
                                          for code, name in zip(("en", "ko", "ja"), MEMBERS[4][:1] + MEMBERS[4][1:])})
        korean = labels.record_label(self.root, record(KOREAN_ONLY))
        self.assertEqual(korean["label"], {"en": "004 Umi Sonoda · 한국어 이름", "ko": "004 소노다 우미 · 한국어 이름",
                                           "ja": "004 園田 海未 · 한국어 이름"})
        for suit, number in ((UNNAMED, "555"), (KEY_ONLY, "556"), (OTHER_KEY, "558")):
            parts = labels.record_label(self.root, record(suit))
            self.assertFalse(parts["named"])
            self.assertEqual(parts["label"], {"en": f"004 Umi Sonoda · Costume #{number}", "ko": f"004 소노다 우미 · 의상 #{number}",
                                              "ja": f"004 園田 海未 · 衣装 #{number}"})
            self.assertNotIn("k.", json.dumps(parts, ensure_ascii=False))
            self.assertNotIn("suit:", json.dumps(parts, ensure_ascii=False))

    def test_only_the_other_view_is_named_and_primary_never_is(self):
        masked = labels.record_label(self.root, record(RINA))
        unmasked = labels.record_label(self.root, record(RINA, "unmasked"))
        self.assertEqual(masked["label"]["ko"], "209 텐노지 리나 · 리나 의상")
        self.assertEqual(unmasked["label"], {"en": "209 Rina Tennoji · Rina outfit · Without mask",
                                             "ko": "209 텐노지 리나 · 리나 의상 · 마스크 없음",
                                             "ja": "209 天王寺 璃奈 · 璃奈の衣装 · マスクなし"})
        # The Mod ZIP holds both views, so the automatic name names neither.
        self.assertEqual(unmasked["nameBase"], masked["nameBase"])
        for parts in (masked, unmasked):
            self.assertNotIn("primary", json.dumps(parts["label"]) + json.dumps(parts["nameBase"]))
            self.assertNotIn("unmasked", json.dumps(parts["label"]) + json.dumps(parts["nameBase"]))

    def test_member_choices_and_automatic_face(self):
        rows = labels.member_choices(self.root, [4, 101, 211])
        self.assertEqual([row["labels"]["ko"] for row in rows], ["004 소노다 우미", "101 타카미 치카", "211 미아 테일러"])
        self.assertEqual(rows[0]["labels"]["ja"], "004 園田 海未")
        face = labels.face_label(self.root, "ch0004_546bb8d07f938f60de66f6f8.unity")
        self.assertEqual(face, {"en": "004 Umi Sonoda · Face (automatic)", "ko": "004 소노다 우미 · 얼굴(자동)",
                                "ja": "004 園田 海未 · 顔（自動）"})
        # Native asset numbers differ for Mia and Lanzhu.
        self.assertEqual(labels.face_label(self.root, "ch0212_546bb8d07f938f60de66f6f8.unity")["ko"], "211 미아 테일러 · 얼굴(자동)")
        self.assertEqual(labels.face_label(self.root, "face.unity")["ko"], "얼굴(자동)")


class CatalogTests(unittest.TestCase):
    """The Game assets list: numbered members; a search names the member."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        build_root(self.root)
        from types import SimpleNamespace
        from unittest.mock import patch
        from webtools.core import game_models
        from webtools.core.charinfo import NAMES

        def real_costume_name(dictionary, key):
            row = dictionary.execute("SELECT message FROM m_dictionary WHERE id=?", (key[2:],)).fetchone() if dictionary else None
            return row[0] if row and row[0] else key
        stub = SimpleNamespace(real_costume_name=real_costume_name, CHARACTERS=NAMES)
        patcher = patch.object(game_models, "_extractor", return_value=stub)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.catalog = game_models.catalog

    def labels(self, **options):
        result = self.catalog(self.root, **options)
        return result, {option["value"]: option["label"] for option in result["costumes"]}

    def test_members_are_numbered_and_named_in_the_page_language(self):
        result, costumes = self.labels(language="ko", character="4")
        self.assertEqual(result["region"], "gl")
        self.assertEqual({row["value"]: row["label"] for row in result["characters"]},
                         {"4": "004 소노다 우미", "209": "209 텐노지 리나"})
        # One member's list names only the costumes, also an added costume
        # installed with this member's number and name; equal names get their number.
        self.assertEqual(costumes[f"suit:{OFFICIAL}"], "오토노키자카 고교 교복(동복)")
        self.assertEqual(costumes[f"suit:{INSTALLED}"], "오토노키자카 고교 교복(동복) · 외곽선 #" + str(INSTALLED))
        self.assertEqual(costumes[f"suit:{COPY}"], "오토노키자카 고교 교복(동복) · 외곽선 #" + str(COPY))
        self.assertEqual(costumes[f"suit:{OLDER}"], "Otonokizaka High Uniform (Winter) · 외곽선")
        self.assertFalse([label for label in costumes.values() if label.startswith("004 ")])
        self.assertEqual((costumes[f"suit:{UNNAMED}"], costumes[f"suit:{KEY_ONLY}"]), ("의상 #555", "의상 #556"))
        result, costumes = self.labels(language="ja", character="4")
        self.assertEqual(result["region"], "jp")
        self.assertEqual(result["characters"][0]["label"], "004 園田 海未")
        self.assertEqual(costumes[f"suit:{OFFICIAL}"], "音ノ木坂学院制服（冬服）")

    def test_search_results_name_number_member_and_costume_once(self):
        _, costumes = self.labels(language="ko", search="Umi")
        self.assertEqual(costumes[f"suit:{OFFICIAL}"], "004 소노다 우미 · 오토노키자카 고교 교복(동복)")
        self.assertEqual(costumes[f"suit:{OLDER}"], "004 소노다 우미 · Otonokizaka High Uniform (Winter) · 외곽선")
        self.assertTrue(costumes[f"suit:{INSTALLED}"].startswith("004 소노다 우미 · 오토노키자카 고교 교복(동복) · 외곽선"))
        self.assertNotIn(f"suit:{RINA}", costumes)
        for query in ("004", "소노다", "리나 의상"):
            _, found = self.labels(language="ko", search=query)
            self.assertTrue(found, query)
        _, found = self.labels(language="ko", search="리나 의상")
        self.assertEqual(found, {f"suit:{RINA}": "209 텐노지 리나 · 리나 의상"})

    def test_search_results_are_listed_by_member_number_in_the_game_order(self):
        result, _ = self.labels(language="en", search="o")
        values = [option["value"] for option in result["costumes"]]
        owners = [SUITS[int(value.split(":")[1])][0] for value in values]
        self.assertIn(209, owners)
        self.assertEqual(owners, sorted(owners), "every 004 row before the 209 row")
        # Within one member the game's own order is kept: as in that member's list.
        _, member = self.labels(language="en", character="4")
        self.assertEqual([value for value in values if SUITS[int(value.split(":")[1])][0] == 4],
                         [value for value in member if value in values])
        # The game's own order (newest first) has Rina's costume among Umi's.
        with sqlite3.connect(self.root / "assets/db/gl/masterdata.db") as db:
            ordered = [row[0] for row in db.execute("SELECT id FROM m_suit ORDER BY display_order DESC")]
        self.assertLess(ordered.index(RINA), len(ordered) - 1)
        self.assertEqual(values[-1], f"suit:{RINA}")


class DescribeTests(unittest.TestCase):
    """Labels follow the server's own receipts; names and folders prove nothing."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "runtime"
        build_root(self.root)
        self.cache = self.base / "cache"
        self.cache.mkdir()

    def write(self, relative, data):
        path = self.base / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path.resolve()

    def imported(self, suit, data, variant="primary"):
        owner = SUITS[suit][0]
        path = self.write(f"cache/gl-{suit}-{variant}/ch{owner:04}_suit{suit}_{variant}.unity", data)
        receipt = {"model": f"gl-{suit}-{variant}/{path.name}", "sha256": hashlib.sha256(data).hexdigest(),
                   "selection_record": record(suit, variant)}
        (self.cache / f".selection-{suit:031d}{int(variant == 'unmasked')}.json").write_text(json.dumps(receipt))
        return path

    def proof(self, parent, member=None):
        raw = parent.read_bytes()
        model = zipfile.ZipFile(parent).read(member) if member else raw
        return {"path": str(parent), "containerSha256": hashlib.sha256(raw).hexdigest(), "member": member,
                "sha256": hashlib.sha256(model).hexdigest()}

    def derived(self, path, parents, operation="costume", **extra):
        from webtools.core import viewer_physics_runtime as runtime
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        proofs = [parent if isinstance(parent, dict) else self.proof(parent) for parent in parents]
        runtime._write_receipts(self.cache, path, [{"member": None, "sha256": digest, "operation": operation,
                                                    "parents": proofs, "components": [], **extra}])

    def describe(self, path):
        return labels.describe(path, repo_root=self.root, cache_root=self.cache)

    def test_game_import_and_its_edited_copy_read_as_the_costume(self):
        original = self.imported(INSTALLED, b"wearer body")
        game = self.describe(original)
        self.assertEqual(game["source"], "game")
        self.assertEqual(game["label"]["ko"], "004 소노다 우미 · 오토노키자카 고교 교복(동복) · 외곽선")
        self.assertEqual(game["file"], f"ch0004_suit{INSTALLED}_primary.unity")
        self.assertEqual(game["counterpart"], {"region": "gl", "suitId": INSTALLED, "variant": "primary", "owner": 4})
        # An edited preview copy keeps the code file name; its receipt names the wearer.
        edited = self.write(f"exports/body-edit-1/models/ch0004_suit{INSTALLED}_primary.unity", b"edited body")
        self.derived(edited, [original], "edit", operations=["edit"])
        copy = self.describe(edited)
        self.assertEqual((copy["source"], copy["label"], copy["suitId"]), ("derived", game["label"], INSTALLED))
        self.assertNotIn("operations", copy)

    def transplant(self, operation, donor, *, wearer=None, name="result", **extra):
        wearer = wearer or self.imported(OFFICIAL, b"umi body")
        result = self.write(f"exports/transplant-{name}/models/ch0004_suit{OFFICIAL}_primary.unity", ("%s %s" % (operation, name)).encode())
        self.derived(result, [wearer, donor], operation, **extra)
        return result

    def test_a_costume_transplant_reads_as_the_wearer_in_the_donor_costume(self):
        donor = self.imported(RINA, b"rina body")
        result = self.describe(self.transplant("costume", donor))
        self.assertEqual(result["label"], {"en": "004 Umi Sonoda · Rina outfit · Costume transplant",
                                           "ko": "004 소노다 우미 · 리나 의상 · 코스튬 이식",
                                           "ja": "004 園田 海未 · 璃奈の衣装 · 衣装移植"})
        self.assertEqual(result["nameBase"]["ko"], result["label"]["ko"])
        self.assertEqual(result["nameText"]["ko"], "리나 의상 · 코스튬 이식")
        # The costume number shown is the donor's; the container (conversion
        # counterpart) and the member stay the wearer's.
        self.assertEqual((result["suitId"], result["owner"], result["operations"]), (RINA, 4, ["costume"]))
        self.assertEqual(result["counterpart"], {"region": "gl", "suitId": OFFICIAL, "variant": "primary", "owner": 4})
        self.assertNotIn("오토노키자카", json.dumps(result["label"], ensure_ascii=False))

    def test_part_and_lower_transplants_keep_the_wearer_costume(self):
        donor = self.imported(RINA, b"rina body")
        for operation, ko in (("part", "코스튬 부분 이식"), ("lower", "하체 교체")):
            with self.subTest(operation=operation):
                result = self.describe(self.transplant(operation, donor, name=operation))
                self.assertEqual(result["label"]["ko"], "004 소노다 우미 · 오토노키자카 고교 교복(동복) · " + ko)
                self.assertEqual((result["suitId"], result["counterpart"]["suitId"]), (OFFICIAL, OFFICIAL))

    def test_edits_of_a_transplant_result_keep_the_costume_it_wears(self):
        from webtools.core import viewer_physics_runtime as runtime
        donor = self.imported(RINA, b"rina body")
        wearer = self.imported(OFFICIAL, b"umi body")
        transplanted = self.transplant("costume", donor, wearer=wearer)
        expected = self.describe(transplanted)["label"]
        # A save of the result reuses its wearer/donor parents. Older edit rows
        # do not name the transplant: the last one they list.
        older = self.write("exports/body-edit-2/models/a.unity", b"older edit")
        self.derived(older, [wearer, donor], "edit", operations=["costume", "edit"])
        self.assertEqual(self.describe(older)["label"], expected)
        newer = self.write("exports/body-edit-3/models/a.unity", b"newer edit")
        self.derived(newer, [wearer, donor], "edit", operations=["part", "costume", "edit"], pairOperation="costume")
        self.assertEqual(self.describe(newer)["label"]["ko"], "004 소노다 우미 · 리나 의상 · 코스튬 부분 이식 · 코스튬 이식")
        # A part transplant onto the costume transplant result: still the donor costume.
        other = self.imported(INSTALLED, b"other umi")
        part = self.write("exports/transplant-part2/models/a.unity", b"part on costume")
        self.derived(part, [transplanted, other], "part")
        self.assertEqual(self.describe(part)["label"]["ko"], "004 소노다 우미 · 리나 의상 · 코스튬 이식 · 코스튬 부분 이식")
        # A second costume transplant: the newest donor's costume is worn.
        again = self.write("exports/transplant-again/models/a.unity", b"costume on costume")
        self.derived(again, [transplanted, other], "costume")
        self.assertEqual(self.describe(again)["label"]["ko"], "004 소노다 우미 · 오토노키자카 고교 교복(동복) · 외곽선 · 코스튬 이식")
        self.assertEqual(self.describe(again)["suitId"], INSTALLED)
        # inherit_export keeps the pairing transplant in the edit rows it writes.
        self.assertEqual(labels.pair_operation({"parents": [{}, {}], "operation": "edit", "operations": ["costume", "part", "edit"],
                                                "pairOperation": "costume"}), "costume")
        self.assertEqual(labels.pair_operation({"parents": [{}, {}], "operation": "edit", "operations": ["costume", "part", "edit"]}), "part")
        self.assertIsNone(labels.pair_operation({"parents": [{}], "operation": "costume"}))
        self.assertIsNone(labels.pair_operation({"parents": [{}, {}], "operation": "edit", "operations": ["edit"]}))
        from unittest.mock import patch
        from webtools.core import viewer_mod_sources
        pair = [self.proof(wearer), self.proof(donor)]
        for previous, expected in (({"operation": "costume", "parents": pair, "components": []}, "costume"),
                                   ({"operation": "edit", "operations": ["costume", "lower", "edit"], "pairOperation": "costume",
                                     "parents": pair, "components": []}, "costume"),
                                   ({"operation": "edit", "operations": ["edit"], "parents": pair[:1], "components": []}, None)):
            with self.subTest(previous=previous["operation"]), \
                    patch.object(runtime, "_source_proofs", return_value=[self.proof(transplanted)]), \
                    patch.object(runtime, "_resolve", return_value={"derived": True, "operations": ["costume"]}), \
                    patch.object(viewer_mod_sources, "_read", return_value=b"saved"), \
                    patch.object(runtime, "_physics_ids", return_value=frozenset()), \
                    patch.object(runtime, "_entry_context", return_value={"sources": [{"raw": b"x"}]}), \
                    patch.object(runtime, "_read_receipt", return_value=previous), \
                    patch.object(runtime, "_write_receipts") as write:
                runtime.inherit_export({"containers": [{}], "sources": [{"container": 0}]}, [str(transplanted)],
                                       repo_root=self.root, cache_root=self.cache)
                row = write.call_args[0][2][0]
                self.assertEqual(row["parents"], previous["parents"])
                self.assertEqual(row.get("pairOperation"), expected)

    def test_a_mod_zip_donor_gives_its_declared_costume_and_an_unnamed_donor_none(self):
        archive = self.base / "donor.zip"
        with zipfile.ZipFile(archive, "w") as handle:
            handle.writestr("modinstall.txt", "chara_id = 101\ncostume_name_en = '101 Chika Takami · Knit'\n"
                                              "costume_name_ko = '101 타카미 치카 · 니트'\ncostume_file = 'a.unity'\n")
            handle.writestr("a.unity", b"chika knit")
        zipped = self.transplant("costume", self.proof(archive, "a.unity"), name="zip")
        result = self.describe(zipped)
        self.assertEqual(result["label"]["ko"], "004 소노다 우미 · 니트 · 코스튬 이식")
        self.assertEqual(result["label"]["en"], "004 Umi Sonoda · Knit · Costume transplant")
        self.assertNotIn("suitId", result)
        # A Mod ZIP replaced after the transplant does not name it.
        with zipfile.ZipFile(archive, "w") as handle:
            handle.writestr("modinstall.txt", "chara_id = 101\ncostume_name_en = 'Other'\ncostume_file = 'a.unity'\n")
            handle.writestr("a.unity", b"chika knit")
        self.assertEqual(self.describe(zipped)["label"]["ko"], "004 소노다 우미 · 코스튬 이식")
        # A donor that changed after the transplant names no costume, never the replaced one.
        gone = self.imported(RINA, b"rina body")
        changed = self.transplant("costume", gone, name="changed")
        gone.write_bytes(b"changed donor")
        result = self.describe(changed)
        self.assertEqual(result["label"]["ko"], "004 소노다 우미 · 코스튬 이식")
        self.assertEqual((result["named"], result["counterpart"]["suitId"]), (False, OFFICIAL))
        self.assertNotIn("suitId", result)

    def test_a_wearer_inside_a_zip_is_not_followed(self):
        archive = self.base / "wearer.zip"
        original = self.imported(OFFICIAL, b"umi body")
        with zipfile.ZipFile(archive, "w") as handle:
            handle.writestr("a.unity", original.read_bytes())
        result = self.write("exports/zipped/models/a.unity", b"from zip")
        self.derived(result, [self.proof(archive, "a.unity")], "edit")
        self.assertEqual(self.describe(result), {"file": result.name})
        # A member name alone already stops the walk, even with matching digests.
        self.derived(result, [{**self.proof(original), "member": "a.unity"}], "edit")
        self.assertEqual(self.describe(result), {"file": result.name})
        # The same row with a plain file parent is followed.
        self.derived(result, [original], "edit")
        self.assertEqual(self.describe(result)["source"], "derived")

    def test_receipts_that_disagree_name_nothing(self):
        path = self.imported(OFFICIAL, b"claimed twice")
        other = json.loads(next(self.cache.glob(".selection-*.json")).read_text())
        other["selection_record"] = record(INSTALLED)
        (self.cache / (".selection-" + "9" * 32 + ".json")).write_text(json.dumps(other))
        self.assertEqual(self.describe(path), {"file": path.name})

    def test_unbound_or_changed_files_keep_their_file_name(self):
        original = self.imported(OFFICIAL, b"official body")
        # A misleading code file name alone names nothing.
        stranger = self.write(f"elsewhere/ch0004_suit{OFFICIAL}_primary.unity", b"someone else's body")
        self.assertEqual(self.describe(stranger), {"file": stranger.name})
        original.write_bytes(b"changed after the receipt")
        self.assertEqual(self.describe(original), {"file": original.name})
        self.assertEqual(self.describe(self.base / "missing.unity"), {"file": "missing.unity"})

    def test_mod_zip_reads_its_declared_names_after_the_member(self):
        def mod(name, values):
            path = self.base / name
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("modinstall.txt", "\n".join(f"{key} = {value!r}" for key, value in values.items()))
                archive.writestr("a.unity", b"body")
            return path
        older = mod("older.zip", {"chara_id": 4, "costume_name_en": "Knit", "costume_name_ko": "니트", "costume_file": "a.unity"})
        parts = self.describe(older)
        self.assertEqual(parts["source"], "manifest")
        self.assertEqual(parts["label"], {"en": "004 Umi Sonoda · Knit", "ko": "004 소노다 우미 · 니트", "ja": "004 園田 海未 · Knit"})
        named = mod("named.zip", {"chara_id": 4, "costume_name_en": "004 Umi Sonoda · Knit",
                                  "costume_name_ko": "004 소노다 우미 · 니트", "costume_file": "a.unity"})
        self.assertEqual(self.describe(named)["label"]["ko"], "004 소노다 우미 · 니트")

    def test_metadata_name_bases_sources_and_members(self):
        path = self.imported(OFFICIAL, b"official body")
        face = self.write("cache/faces/ch0004_546bb8d07f938f60de66f6f8.unity", b"face")
        containers = [{"name": path.name, "path": str(path), "raw": path.read_bytes(), "sha256": hashlib.sha256(b"official body").hexdigest()},
                      {"name": face.name, "path": str(face), "raw": b"face", "sha256": hashlib.sha256(b"face").hexdigest()}]
        context = {"containers": containers, "sources": [{"container": 0, "member": None}, {"container": 1, "member": None}],
                   "outline_only_sources": [1]}
        result = flow.metadata(context, repo_root=self.root, cache_root=self.cache, language="ko")
        self.assertEqual(result["nameBase"], "004 소노다 우미 · 오토노키자카 고교 교복(동복)")
        self.assertEqual(result["nameBases"]["ja"], "004 園田 海未 · 音ノ木坂学院制服（冬服）")
        self.assertEqual([row["label"]["ko"] for row in result["sources"]],
                         ["004 소노다 우미 · 오토노키자카 고교 교복(동복)", "004 소노다 우미 · 얼굴(자동)"])
        self.assertEqual(result["sources"][0]["file"], path.name)
        umi = next(row for row in result["characters"] if row["value"] == "4")
        self.assertEqual((umi["label"], umi["labels"]["ko"]), ("004 Umi Sonoda", "004 소노다 우미"))
        # Nothing names a third-party file: its file name stays the base.
        other = self.write("elsewhere/my_costume.unity", b"other")
        context = {"containers": [{"name": other.name, "path": str(other), "raw": b"other",
                                   "sha256": hashlib.sha256(b"other").hexdigest()}],
                   "sources": [{"container": 0, "member": None, "sha256": hashlib.sha256(b"other").hexdigest()}]}
        self.assertEqual(flow.metadata(context, repo_root=self.root, cache_root=self.cache)["nameBases"]["ko"], "my_costume")
        # The same file of a known member (from its model): number and member, then the file name.
        from unittest.mock import patch
        from webtools.core import viewer_mod_sources
        with patch.object(viewer_mod_sources, "_model_facts", return_value={"owner": 4}):
            known = flow.metadata(context, repo_root=self.root, cache_root=self.cache, language="ko")
        self.assertEqual((known["characterId"], known["nameBase"]), (4, "004 소노다 우미 · my_costume"))
        self.assertEqual(known["nameBases"]["ja"], "004 園田 海未 · my_costume")

    def test_metadata_for_a_verified_game_binding(self):
        add_asset_catalog(self.root)
        data = b"bound official body"
        path = self.imported(OFFICIAL, data)
        receipt = next(self.cache.glob(".selection-*.json"))
        value = json.loads(receipt.read_text())
        value["selection_record"] = selection(self.root)
        receipt.write_text(json.dumps(value))
        context = {"containers": [{"name": path.name, "path": str(path), "raw": data, "sha256": hashlib.sha256(data).hexdigest()}],
                   "sources": [{"container": 0, "member": None, "sha256": hashlib.sha256(data).hexdigest()}]}
        from webtools.core import viewer_mod_sources
        self.assertEqual(len(viewer_mod_sources.game_context(context, self.root, receipts=flow.cached_receipts(context, self.cache))), 1)
        result = flow.metadata(context, repo_root=self.root, cache_root=self.cache, language="ja")
        self.assertEqual(result["characterId"], 4)
        self.assertEqual(result["nameBase"], "004 園田 海未 · 音ノ木坂学院制服（冬服）")
        self.assertEqual((result["sources"][0]["source"], result["sources"][0]["suitId"]), ("game", OFFICIAL))
        # The verified game costume rides along in the Mod ZIP as an inert record.
        self.assertEqual(flow._source_costume(result), {"region": "gl", "suit_id": OFFICIAL, "variant": "primary", "member": 4})

    def context(self, path):
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        return {"containers": [{"name": path.name, "path": str(path), "raw": raw, "sha256": digest}],
                "sources": [{"container": 0, "member": None, "sha256": digest}]}

    def metadata(self, path, language="ko"):
        return flow.metadata(self.context(path), repo_root=self.root, cache_root=self.cache, language=language)

    def test_metadata_name_base_never_names_the_rina_view(self):
        unmasked = self.metadata(self.imported(RINA, b"rina unmasked", "unmasked"))
        self.assertEqual(unmasked["sources"][0]["label"]["ko"], "209 텐노지 리나 · 리나 의상 · 마스크 없음")
        self.assertEqual(unmasked["nameBase"], "209 텐노지 리나 · 리나 의상")
        self.assertEqual(unmasked["nameBases"]["ja"], "209 天王寺 璃奈 · 璃奈の衣装")

    def test_another_mod_member_gets_its_own_number_and_name(self):
        meta = self.metadata(self.imported(OFFICIAL, b"umi body"))
        self.assertEqual((meta["nameOwner"], meta["nameTexts"]["ko"]), (4, "오토노키자카 고교 교복(동복)"))
        self.assertEqual(flow.name_bases(meta, 4, repo_root=self.root), meta["nameBases"])
        self.assertEqual(flow.name_bases(meta, None, repo_root=self.root), meta["nameBases"])
        chika = flow.name_bases(meta, 101, repo_root=self.root)
        self.assertEqual(chika, {"en": "101 Chika Takami · Otonokizaka High Uniform (Winter)",
                                 "ko": "101 타카미 치카 · 오토노키자카 고교 교복(동복)",
                                 "ja": "101 高海 千歌 · 音ノ木坂学院制服（冬服）"})
        # The same choice label the page puts first.
        choice = next(row for row in meta["characters"] if row["value"] == "101")
        self.assertTrue(chika["ko"].startswith(choice["labels"]["ko"] + " · "))
        # An added costume installed for Umi carries no second member for Chika.
        installed = self.metadata(self.imported(INSTALLED, b"installed umi"))
        self.assertEqual(installed["nameTexts"]["ko"], "오토노키자카 고교 교복(동복) · 외곽선")
        names = flow.localized_mod_names("101 타카미 치카 · 오토노키자카 고교 교복(동복) · 외곽선", [[{"k": "Outlines"}]],
                                         flow.name_bases(installed, 101, repo_root=self.root), "ko")
        self.assertEqual(names["ja"], "101 高海 千歌 · 音ノ木坂学院制服（冬服） · 輪郭線")
        self.assertFalse(any("소노다" in value or "Umi" in value or "園田" in value for value in names.values()))
        # The source member's own bases do not match the page's Chika name.
        self.assertIsNone(flow.localized_mod_names("101 타카미 치카 · 오토노키자카 고교 교복(동복) · 외곽선",
                                                   [[{"k": "Outlines"}]], installed["nameBases"], "ko"))
        # A file nothing names: its file name after the chosen member.
        other = self.write("elsewhere/my_costume.unity", b"other")
        plain = self.metadata(other)
        self.assertEqual((plain["nameOwner"], plain["nameTexts"]["ko"], plain["nameBase"]), (None, "my_costume", "my_costume"))
        self.assertEqual(flow.name_bases(plain, 101, repo_root=self.root)["ko"], "101 타카미 치카 · my_costume")

    def test_derived_and_reopened_sources_keep_their_conversion_record(self):
        wearer = self.imported(OFFICIAL, b"umi body")
        donor = self.imported(RINA, b"rina body")
        record = {"region": "gl", "suit_id": OFFICIAL, "variant": "primary", "member": 4}
        edited = self.write("exports/body-edit-9/models/a.unity", b"edited")
        self.derived(edited, [wearer], "edit")
        self.assertEqual(flow._source_costume(self.metadata(edited)), record)
        # A costume transplant result is the wearer's container (what a
        # conversion matches), although it shows the donor's costume.
        transplanted = self.metadata(self.transplant("costume", donor, wearer=wearer))
        self.assertEqual(transplanted["nameBase"], "004 소노다 우미 · 리나 의상 · 코스튬 이식")
        self.assertEqual(flow._source_costume(transplanted), record)
        # A reopened viewer Mod ZIP carries its own record on; one without none.
        from webtools.core import viewer_mod_package as packages
        def mod(name, extra):
            path = self.base / name
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("modinstall.txt", "chara_id = 4\ncostume_name_en = 'Knit'\ncostume_file = 'a.unity'\n")
                archive.writestr("a.unity", b"body")
                for member, value in extra.items():
                    archive.writestr(member, value)
            return path
        kept = mod("kept.zip", {"metadata/" + packages.SOURCE_COSTUME_MEMBER:
                                json.dumps({"format": packages.SOURCE_COSTUME_FORMAT, "version": 1, **record})})
        reopened = self.metadata(kept)
        self.assertEqual(reopened["sources"][0]["source"], "manifest")
        self.assertEqual(flow._source_costume(reopened), record)
        self.assertIsNone(flow._source_costume(self.metadata(mod("plain.zip", {}))))
        # Only a source this server named can give a record.
        self.assertIsNone(flow._source_costume({"sources": [{"kind": "body", "source": "scene", "counterpart": {
            "region": "gl", "suitId": OFFICIAL, "variant": "primary", "owner": 4}}]}))
        self.assertIsNone(flow._source_costume({"sources": [{"kind": "body", "source": "game", "counterpart": {
            "region": "kr", "suitId": OFFICIAL, "variant": "primary", "owner": 4}}]}))


class SourceCostumeRecordTests(unittest.TestCase):
    def test_a_mod_zip_record_is_read_back_only_as_a_well_formed_candidate(self):
        import io
        from webtools.core import costume_platform_source as conversion, viewer_mod_package as packages
        good = {"format": packages.SOURCE_COSTUME_FORMAT, "version": 1, "region": "gl", "suit_id": OFFICIAL, "variant": "primary", "member": 4}

        def read(value, name="metadata/" + packages.SOURCE_COSTUME_MEMBER, extra=()):
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w") as archive:
                archive.writestr(name, value if isinstance(value, bytes) else json.dumps(value))
                for other in extra:
                    archive.writestr(other, json.dumps(good))
            with zipfile.ZipFile(buffer) as archive:
                return conversion._archive_source_costume(archive, {info.filename: info for info in archive.infolist()})
        self.assertEqual(read(good), {"region": "gl", "suit_id": OFFICIAL, "variant": "primary", "member": 4})
        for bad in (dict(good, version=2), dict(good, format="other"), dict(good, region="kr"), dict(good, suit_id="1"),
                    dict(good, suit_id=True), dict(good, variant="masked"), dict(good, member=None), b"\xff", b"[]"):
            with self.subTest(bad=bad):
                self.assertIsNone(read(bad))
        self.assertIsNone(read(good, extra=["metadata2/" + packages.SOURCE_COSTUME_MEMBER]), "two records name nothing")
        self.assertIsNone(read(good, name="source-costume.json"), "only the inert member name counts")


def member_body(owner=4):
    """A native Android costume body whose root prefab is the member's."""
    import UnityPy
    from test_viewer_transplants import costume_fixture
    env = UnityPy.load(costume_fixture(13, body_owner=owner))
    for obj in env.objects:
        if obj.type.name == "AssetBundle":
            tree = obj.read_typetree()
            prefab = f"assets/llas/resources/characters/models/ch{owner:04}/ch{owner:04}_co0001_member.prefab"
            tree["m_Container"] = [(prefab, value) for _, value in tree["m_Container"]]
            obj.save_typetree(tree)
    return env.file.save()


class PlatformConversionRecordTests(unittest.TestCase):
    """A readable-named viewer Mod ZIP converts through its source record.

    No asset extractor is needed: the game catalog checks that need packs
    (validate_selection, the original body's identity) are stood in for;
    the ZIP, its manifest, the record and the candidate rules are real.
    """

    def setUp(self):
        import os
        from unittest.mock import patch
        from webtools.core import costume_platform_source as conversion, game_models, viewer_mod_package as packages
        self.conversion, self.game, self.packages = conversion, game_models, packages
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "runtime"
        build_root(self.root)
        for region in ("gl", "jp"):
            with sqlite3.connect(self.root / "assets/db" / region / "masterdata.db") as db:
                db.execute("UPDATE m_suit SET model_asset_path=? WHERE id=?", (f"m/{OFFICIAL}", OFFICIAL))
        self.library = self.base / "library"
        (self.library / "mods").mkdir(parents=True)
        environment = patch.dict(os.environ, {"SUKUSTA_DIR": str(self.library)})
        environment.start()
        self.addCleanup(environment.stop)
        self.body = self.base / "work" / "ch0004_suit100041001_primary.unity"
        self.body.parent.mkdir()
        self.body.write_bytes(member_body(4))
        self.checked = []

        def validate(root, selection, language):
            suit = int(selection["suit"].split(":")[1])
            self.checked.append((selection["region"], suit, selection["variant"], selection["platform"]))
            if suit != OFFICIAL or selection["variant"] != "primary":
                raise ValueError("not this costume")
            return {"region": selection["region"], "suit_id": suit, "variant": "primary", "owner": 4,
                    "model": f"m/{OFFICIAL}", "platform": selection["platform"], "selection_language": language}
        self.identity = None

        def matches(root, record, packs, identity):
            self.identity = identity
            return record["model"] == f"m/{OFFICIAL}"
        from types import SimpleNamespace
        from webtools.core.charinfo import NAMES

        def real_costume_name(dictionary, key):
            row = dictionary.execute("SELECT message FROM m_dictionary WHERE id=?", (key[2:],)).fetchone() if dictionary else None
            return row[0] if row and row[0] else key
        for target, attribute, replacement in (
                (game_models, "validate_selection", validate), (conversion, "_matches_local_identity", matches),
                (conversion, "_availability", lambda *args: []),
                (game_models, "_extractor", lambda: SimpleNamespace(real_costume_name=real_costume_name, CHARACTERS=NAMES))):
            patcher = patch.object(target, attribute, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

    def package(self, name, *, names=None, source=None, character=4):
        result = self.packages.package_saved_export({"preview_paths": [str(self.body)], "originals_preserved": True},
                                                    self.base / "out" / name, display_name=name, chara_id=character,
                                                    **({"names": names} if names else {}),
                                                    **({"source_costume": source} if source else {}))
        target = self.library / "mods" / (name + ".zip")
        Path(result["package_path"]).replace(target)
        return target

    def resolve(self, path, region="gl"):
        return self.conversion.resolve(self.root, {"path": str(path), "direction": "android_to_ios", "region": region},
                                       language="ko", cache_root=self.base / "cache")

    def test_a_readable_named_zip_matches_through_its_source_record(self):
        names = {"en": "004 Umi Sonoda · Otonokizaka High Uniform (Winter) · Outlines",
                 "ko": "004 소노다 우미 · 오토노키자카 고교 교복(동복) · 외곽선",
                 "ja": "004 園田 海未 · 音ノ木坂学院制服（冬服） · 輪郭線"}
        record = {"region": "gl", "suit_id": OFFICIAL, "variant": "primary", "member": 4}
        path = self.package(names["ko"], names=names, source=record)
        # The record is read back from the packaged ZIP itself.
        raw, member, declared, source = self.conversion._read_archive_body(path, "android")
        self.assertEqual(source, record)
        self.assertNotRegex(" ".join(declared), r"ch\d{4}_suit")
        result = self.resolve(path)
        self.assertEqual(result["status"], "matched", result.get("message"))
        self.assertEqual((result["selection"]["suit"], result["selection"]["variant"], result["selection"]["platform"]),
                         (f"suit:{OFFICIAL}", "primary", "ios"))
        self.assertEqual(self.identity[:2], (4, "assets/llas/resources/characters/models/ch0004/ch0004_co0001_member.prefab"))
        # The match is labelled like the viewer's other model names.
        self.assertEqual(result["label"], "004 소노다 우미 · 오토노키자카 고교 교복(동복)")
        # Without the record nothing names this body's costume.
        plain = self.package(names["ko"] + " copy", names={code: value + " copy" for code, value in names.items()})
        self.assertEqual(self.resolve(plain)["status"], "unknown")

    def test_a_record_for_another_region_or_member_is_ignored(self):
        for name, record in (("jp", {"region": "jp", "suit_id": OFFICIAL, "variant": "primary", "member": 4}),
                             ("chika", {"region": "gl", "suit_id": OFFICIAL, "variant": "primary", "member": 101})):
            with self.subTest(record=name):
                self.checked.clear()
                path = self.package("Knit " + name, source=record, character=record["member"])
                self.assertEqual(self.resolve(path)["status"], "unknown")
                self.assertFalse([row for row in self.checked if row[3] == "android"], "the record was never a candidate")
        # The same JP record matches a JP conversion.
        path = self.package("Knit jp2", source={"region": "jp", "suit_id": OFFICIAL, "variant": "primary", "member": 4})
        self.assertEqual(self.resolve(path, "jp")["status"], "matched")

    def test_an_older_code_name_still_matches_after_a_readable_prefix(self):
        for name in ("ch0004_suit100041001_primary · Outlines", "004 Umi Sonoda · ch0004_suit100041001_primary · Outlines"):
            with self.subTest(name=name):
                result = self.resolve(self.package(name))
                self.assertEqual(result["status"], "matched")
        # A hint inside a longer word, or another member's hint, is no candidate.
        for name in ("xch0004_suit100041001_primary", "ch0101_suit100041001_primary"):
            with self.subTest(name=name):
                self.assertEqual(self.resolve(self.package(name))["status"], "unknown")


class LabelRouteTests(unittest.TestCase):
    """POST /api/viewer/model-labels: allowed files only, bounded, display only."""

    def setUp(self):
        import os
        import threading
        from http.server import ThreadingHTTPServer
        from unittest.mock import patch
        from webtools.core.viewer_cache import game_models_dir
        from webtools.server import Handler
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.library = Path(temporary.name) / "library"
        environment = patch.dict(os.environ, {"SUKUSTA_DIR": str(self.library)})
        environment.start()
        self.addCleanup(environment.stop)
        cache = game_models_dir()
        self.bound = cache / "gl-route" / f"ch0004_suit{OFFICIAL}_primary.unity"
        self.bound.parent.mkdir(parents=True)
        self.bound.write_bytes(b"route body")
        receipt = {"model": "gl-route/" + self.bound.name, "sha256": hashlib.sha256(b"route body").hexdigest(), "selection_record": record(OFFICIAL)}
        (cache / (".selection-" + "2" * 32 + ".json")).write_text(json.dumps(receipt))
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(lambda: (self.server.shutdown(), self.server.server_close(), thread.join(3)))

    def post(self, body, **headers):
        import http.client
        host = "127.0.0.1:" + str(self.server.server_port)
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        try:
            connection.request("POST", "/api/viewer/model-labels?lang=ko", body=json.dumps(body),
                               headers={"Host": host, "Origin": "http://" + host, "Content-Type": "application/json", **headers})
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def test_labels_for_allowed_files_and_names_only_for_others(self):
        outside = Path(__file__).resolve()
        status, data = self.post({"paths": [str(self.bound), str(outside), str(self.library / "missing.unity")]})
        self.assertEqual(status, 200, data)
        bound, other, missing = data["labels"]
        self.assertEqual((bound["path"], bound["source"], bound["suitId"], bound["file"]), (str(self.bound), "game", OFFICIAL, self.bound.name))
        # Without the game's dictionaries the member falls back to the roster and the costume to its number.
        self.assertEqual(bound["label"]["ko"], "004 Umi Sonoda · 의상 #100041001")
        self.assertEqual(other, {"path": str(outside), "file": outside.name})
        self.assertEqual(missing, {"path": str(self.library / "missing.unity"), "file": "missing.unity"})
        # A file outside the allowed folders is never read, even when a receipt names it.
        hidden = self.library.parent / "outside" / self.bound.name
        hidden.parent.mkdir()
        hidden.write_bytes(b"route body")
        receipt = {"path": str(hidden.resolve()), "sha256": hashlib.sha256(b"route body").hexdigest(), "record": record(OFFICIAL)}
        key = hashlib.sha256(str(hidden.resolve()).encode()).hexdigest()[:32]
        (self.bound.parent.parent / (".provenance-" + key + ".json")).write_text(json.dumps(receipt))
        from webtools.core import model_labels as direct
        from webtools.core.viewer_cache import game_models_dir
        self.assertEqual(direct.describe(hidden, repo_root=self.library, cache_root=game_models_dir())["source"], "game")
        status, data = self.post({"paths": [str(hidden)]})
        self.assertEqual(data["labels"], [{"path": str(hidden), "file": hidden.name}])

    def test_mv_studio_costume_asset_is_listed_by_its_label(self):
        from types import SimpleNamespace
        from webtools.server import Handler
        handler = SimpleNamespace(_lang=lambda: "ko")
        result = {"asset": {"kind": "outfit", "label": self.bound.name, "path": self.bound.name}, "performer": {"label": self.bound.name}}
        Handler._label_mv_costume(handler, result, str(self.bound))
        self.assertEqual((result["asset"]["label"], result["performer"]["label"]), ("004 Umi Sonoda · 의상 #100041001",) * 2)
        self.assertEqual(result["asset"]["path"], self.bound.name)
        stage = {"asset": {"kind": "stage", "label": "stage.unity"}}
        Handler._label_mv_costume(handler, stage, str(self.bound))
        self.assertEqual(stage["asset"]["label"], "stage.unity")
        outside = {"asset": {"kind": "outfit", "label": "x.unity"}}
        Handler._label_mv_costume(handler, outside, str(Path(__file__).resolve()))
        self.assertEqual(outside["asset"]["label"], "x.unity")

    def test_requests_are_bounded_and_same_origin(self):
        for body in ({"paths": []}, {"paths": "x"}, {"paths": [str(self.bound)] * 17}, {"paths": [""]}, {"paths": ["a\0b"]},
                     {"paths": [str(self.bound)], "extra": 1}):
            with self.subTest(body=str(body)[:40]):
                self.assertEqual(self.post(body)[0], 400)
        self.assertEqual(self.post({"paths": [str(self.bound)]}, **{"Sec-Fetch-Site": "cross-site"})[0], 403)


class ModNameTests(unittest.TestCase):
    def test_automatic_name_per_language_and_no_repeated_labels(self):
        bases = {"en": "004 Umi Sonoda · Otonokizaka High Uniform (Winter)", "ko": "004 소노다 우미 · 오토노키자카 고교 교복(동복)",
                 "ja": "004 園田 海未 · 音ノ木坂学院制服（冬服）"}
        parts = [[{"k": "Outlines"}], [{"k": "Costume transplant"}]]
        names = flow.localized_mod_names("004 소노다 우미 · 오토노키자카 고교 교복(동복) · 외곽선 · 코스튬 이식", parts, bases, "ko")
        self.assertEqual(names, {"en": "004 Umi Sonoda · Otonokizaka High Uniform (Winter) · Outlines · Costume transplant",
                                 "ko": "004 소노다 우미 · 오토노키자카 고교 교복(동복) · 외곽선 · 코스튬 이식",
                                 "ja": "004 園田 海未 · 音ノ木坂学院制服（冬服） · 輪郭線 · 衣装移植"})
        # An installed Mod's name already ends with its kind: not added twice.
        self.assertEqual(flow.compose_mod_name("004 소노다 우미 · 오토노키자카 고교 교복(동복) · 외곽선", [[{"k": "Outlines"}]], "ko"),
                         "004 소노다 우미 · 오토노키자카 고교 교복(동복) · 외곽선")
        # A typed or changed name is installed as typed for every language.
        self.assertIsNone(flow.localized_mod_names("내 의상", parts, bases, "ko"))

    def test_the_120_unit_limit_counts_utf16_like_the_page(self):
        # 8 + 2 * 55 = 118 UTF-16 units (55 code points): " · 외곽선" (6) no longer fits.
        base = "004 X · " + "\U0001D49C" * 55
        self.assertEqual(flow._utf16_length(base), 118)
        self.assertEqual(flow.compose_mod_name(base, [[{"k": "Outlines"}]], "ko"), base)
        shorter = "004 X · " + "\U0001D49C" * 53
        self.assertEqual(flow.compose_mod_name(shorter, [[{"k": "Outlines"}]], "ko"), shorter + " · 외곽선")
        # A cut never splits a surrogate pair.
        self.assertEqual(flow.compose_mod_name("\U0001D49C" * 61, [], "ko"), "\U0001D49C" * 60)

    def test_localized_names_are_checked_like_a_typed_name(self):
        bases = {"en": "004 Umi Sonoda · Winter", "ko": "004 소노다 우미 · 동복", "ja": "004 園田 海未 · 冬服\x7f"}
        self.assertIsNone(flow.localized_mod_names("004 소노다 우미 · 동복", [], bases, "ko"))
        bases["ja"] = "004 園田 海未 · 冬服"
        self.assertEqual(flow.localized_mod_names("004 소노다 우미 · 동복", [], bases, "ko")["ja"], "004 園田 海未 · 冬服")

    def test_a_reopened_scene_is_named_after_its_target_member(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        build_root(root)
        self.assertEqual(flow.scene_name_bases(root, {"display_name": "Board", "target_member_id": 4})["ko"], "004 소노다 우미 · Board")
        self.assertEqual(flow.scene_name_bases(root, {"display_name": "Board"})["ja"], "209 天王寺 璃奈 · Board")
        self.assertEqual(flow.scene_name_bases(root, {"display_name": "Board", "target_member_id": 209})["en"], "209 Rina Tennoji · Board")

    def test_mod_zip_names_start_with_date_then_member_number(self):
        from datetime import datetime
        when = datetime(2026, 11, 28, 1, 19)
        self.assertEqual(flow.mod_zip_stem("004 소노다 우미 · 오토노키자카 고교 교복(동복) · 외곽선", 4, "android", when=when),
                         "2026-11-28_0119_004_소노다_우미_오토노키자카_고교_교복_동복_외곽선_android")
        self.assertEqual(flow.mod_zip_stem("004 園田 海未 · 音ノ木坂学院制服（冬服） · 輪郭線", 4, "ios", when=when),
                         "2026-11-28_0119_004_園田_海未_音ノ木坂学院制服_冬服_輪郭線_ios")
        self.assertEqual(flow.mod_zip_stem("101 타카미 치카 · 의상", 101, "android+ios", when=when),
                         "2026-11-28_0119_101_타카미_치카_의상_android-ios")
        # A typed name gets the number and the romanised given name.
        self.assertEqual(flow.mod_zip_stem("Knit reform", 208, "android", when=when), "2026-11-28_0119_208_Emma_Knit_reform_android")
        self.assertEqual(flow.mod_zip_stem("Emma knit", 208, "android", when=when), "2026-11-28_0119_208_Emma_knit_android")
        self.assertEqual(flow.mod_zip_stem("0042 Winter", 4, None, when=when), "2026-11-28_0119_004_Umi_0042_Winter")
        self.assertEqual(flow.mod_zip_stem("Winter", None, None, when=when), "2026-11-28_0119_Winter")
        self.assertEqual(flow.mod_zip_stem("Winter", 999, None, when=when), "2026-11-28_0119_Winter")

    def test_mod_zip_names_are_safe_on_android_macos_and_windows(self):
        from datetime import datetime
        when = datetime(2026, 11, 28, 1, 19)
        unsafe = '004 CON <a>:"b"/c\\d|e?f*g\x01 . '
        stem = flow.mod_zip_stem(unsafe, 4, "android", when=when)
        self.assertEqual(stem, "2026-11-28_0119_004_CON_a_b_c_d_e_f_g_android")
        self.assertFalse(set(stem) & set('<>:"/\\|?*') or any(ord(char) < 32 for char in stem))
        long = flow.mod_zip_stem("004 소노다 우미 · " + "가" * 120, 4, "android+ios", scene=True, when=when)
        self.assertLessEqual(len(long.encode("utf-8")) + len("_999.zip"), 255)
        self.assertTrue(long.startswith("2026-11-28_0119_004_소노다_우미_") and long.endswith("_android-ios_scene"))
        self.assertEqual(flow.mod_zip_stem("..", 4, None, when=when), "2026-11-28_0119_004_Umi_costume")


if __name__ == "__main__":
    unittest.main()
