"""MV performer/suit resolution following the client's deck chain, and suit attach data."""

from contextlib import closing
from pathlib import Path
import json
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from webtools.core import mv_studio_suit_attach as attach
from webtools.core import mv_studio_suits as suits


MASTER = """
CREATE TABLE m_live_member_mapping (mapping_id INTEGER, position INTEGER, member_master_id INTEGER,
    is_center INTEGER, card_position INTEGER, suit_master_id INTEGER);
CREATE TABLE m_live_override_member_mapping (mapping_id INTEGER, position INTEGER, member_master_id INTEGER,
    member_non_playable_master_id INTEGER, is_center INTEGER, card_position INTEGER, suit_master_id INTEGER,
    suit_non_playable_master_id INTEGER);
CREATE TABLE m_suit (id INTEGER PRIMARY KEY, member_m_id INTEGER, name TEXT, model_asset_path TEXT, display_order INTEGER);
CREATE TABLE m_suit_non_playable (id INTEGER PRIMARY KEY, member_m_id INTEGER, name TEXT, model_asset_path TEXT);
CREATE TABLE m_member_init (member_m_id INTEGER PRIMARY KEY, suit_m_id INTEGER);
CREATE TABLE m_suit_view (suit_master_id INTEGER, view_status INTEGER, model_asset_path TEXT);
CREATE TABLE m_suit_attach (suit_master_id INTEGER PRIMARY KEY, original_suit_master_id INTEGER, attach_key TEXT);
-- 12035-like: Mia (211) solo; the mapping suit is an awakened card suit, m_member_init the winter uniform.
INSERT INTO m_live_member_mapping VALUES (35, 1, 211, 1, 1, 102112001);
INSERT INTO m_suit VALUES (102111001, 211, 'k.winter', 'winter211', 9), (102112001, 211, 'k.card', 'card211', 8),
    (202113001, 211, 'k.stage', 'stage211', 7), (202113101, 211, 'k.stagec1', 'stage211', 6),
    (302092002, 209, 'k.analog', 'board209', 5), (102091001, 209, 'k.winter209', 'winter209', 4),
    (102012001, 201, 'k.winter201', 'winter201', 3), (102102001, 210, 'k.winter210', 'winter210', 2);
INSERT INTO m_member_init VALUES (211, 102111001), (209, 102091001), (201, 102012001), (210, 102102001);
INSERT INTO m_suit_view VALUES (302092002, 2, 'face209'), (102091001, 2, 'winterface209');
INSERT INTO m_suit_attach VALUES (202113101, 202113001, 'c1');
-- 12053-like: the override mapping adds position 1 to the regular mapping.
INSERT INTO m_live_member_mapping VALUES (53, 2, 201, 0, 2, 102012001), (53, 3, 209, 0, 3, 302092002);
INSERT INTO m_live_override_member_mapping VALUES (53, 1, 210, NULL, 1, 1, NULL, NULL);
-- 13002-like: only non-playable members.
INSERT INTO m_live_override_member_mapping VALUES (92, 1, NULL, 991, 1, 1, NULL, 109913001);
INSERT INTO m_suit_non_playable VALUES (109913001, 991, NULL, 'np991'), (109913002, 991, NULL, 'np991b');
"""


class SuitChainTests(unittest.TestCase):
    def setUp(self):
        self.master = sqlite3.connect(":memory:")
        self.master.executescript(MASTER)
        self.addCleanup(self.master.close)

    def chain(self, mapping, deck=None):
        deck_type = (deck or {}).get("deckType", suits.DEFAULT_DECK)
        rows = suits.members_by_position(suits.mapping(self.master, mapping), deck_type, deck)
        return {position: (row["member"],) + suits.suit_for(self.master, row, deck_type, deck)
                for position, row in sorted(rows.items())}

    def test_new_player_customize_deck_wears_the_member_init_suit(self):
        # LiveMvDM.GetSuitMasterIdByPos b__12: no custom deck row -> m_member_init. The CI
        # account showed 12035 Mia in 102111001 (ch0212_co0002), not the mapping's 102112001.
        self.assertEqual(suits.DEFAULT_DECK, suits.DECK_CUSTOM)
        self.assertEqual(self.chain(35), {1: (211, 102111001, "memberInit")})
        self.assertEqual(suits.costume(self.master, 102111001), ("winter211", 1))

    def test_original_deck_wears_the_owned_mapping_suit(self):
        # b__7: original deck suit -> mapping suit the player owns -> m_member_init.
        self.assertEqual(self.chain(35, {"deckType": 1}), {1: (211, 102112001, "mapping")})
        self.assertEqual(self.chain(35, {"deckType": 1, "ownedSuits": frozenset({102111001})}),
                         {1: (211, 102111001, "memberInit")})
        saved = {"deckType": 1, "original": {"members": [211], "suits": [202113001]}}
        self.assertEqual(self.chain(35, saved), {1: (211, 202113001, "deck")})
        # A deck suit of another member is never worn.
        saved["original"]["suits"] = [302092002]
        self.assertEqual(self.chain(35, saved), {1: (211, 102112001, "mapping")})

    def test_customize_deck_members_and_suits(self):
        # GetMemberMasterIdByPos (custom): saved slots first; an empty slot takes the next
        # mapping member (position order) the deck does not already hold.
        saved = {"deckType": 2, "custom": {"members": [None, 210, None], "suits": [None, 102102001, 102012001]}}
        self.assertEqual(self.chain(53, saved), {
            1: (201, 102012001, "deck"),   # slot 3's suit belongs to 201: any slot of that member
            2: (210, 102102001, "deck"),
            3: (209, 102091001, "memberInit"),  # never the mapping suit on the custom deck
        })

    def test_override_mapping_is_concatenated_and_non_playables_resolve(self):
        self.assertEqual(self.chain(53), {1: (210, 102102001, "memberInit"), 2: (201, 102012001, "memberInit"),
                                          3: (209, 102091001, "memberInit")})
        self.assertEqual(self.chain(53, {"deckType": 1})[1], (210, 102102001, "memberInit"))
        rows = suits.mapping(self.master, 92)
        self.assertEqual([(row["member"], row["nonPlayable"], row["suit"]) for row in rows], [(991, True, 109913001)])
        # No m_member_init row: SuitNonPlayableMaster.Select("WHERE member_m_id = ?").First().
        self.assertEqual(self.chain(92), {1: (991, 109913001, "nonPlayable")})
        self.assertEqual(suits.costume(self.master, 109913001), ("np991", 1))

    def test_view_status_model_and_attach_key(self):
        # GetMvLiveMember3DAssetVOs b__1: m_suit_view(suit, u_member.view_status) replaces the
        # model only when the row exists; otherwise the view status is 1.
        self.assertEqual(suits.costume(self.master, 302092002), ("board209", 1))
        self.assertEqual(suits.costume(self.master, 302092002, 2), ("face209", 2))
        self.assertEqual(suits.costume(self.master, 302092002, 3), ("board209", 1))
        self.assertEqual(suits.views(self.master, 302092002), [2])
        self.assertEqual(suits.view_status({"members": {209: {"viewStatus": 2}}}, 209), 2)
        self.assertEqual((suits.attach_key(self.master, 202113101), suits.attach_key(self.master, 202113001)), ("c1", ""))
        self.assertEqual(suits.costume(self.master, 202113101), ("stage211", 1))

    def test_normalizes_requested_deck_state(self):
        deck = suits.normalize_deck({"deckType": 1, "custom": {"members": [211, None], "suits": [102111001]},
                                     "ownedSuits": [102111001], "members": {"209": {"viewStatus": 2}}})
        self.assertEqual((deck["deckType"], deck["ownedSuits"], deck["members"]), (1, frozenset({102111001}), {209: {"viewStatus": 2}}))
        self.assertIsNone(suits.normalize_deck(None))
        for value in ({"deckType": 3}, {"deckType": 1, "extra": 1}, {"custom": {"suits": ["x"]}},
                      {"custom": {"suits": [1] * 13}}, {"members": {"209": {"viewStatus": 0}}}, {"userId": "7"},
                      {"ownedSuits": "all"}, []):
            with self.subTest(value=value), self.assertRaises(ValueError):
                suits.normalize_deck(value)

    def test_provenance_records_the_deck_player_and_each_positions_suit_source(self):
        performers = [{"position": 1, "memberId": 211, "costumeId": 202113101, "viewStatus": 1, "suitSource": "deck",
                       "attachKey": "c1", "model": {"asset": "stage211"}},
                      {"position": 2, "memberId": 209, "costumeId": 302092002, "viewStatus": 2, "suitSource": "pinned",
                       "attachKey": ""}]
        self.assertEqual(suits.provenance({"deckType": 2, "userId": 7, "saved": True}, performers), {
            "deck": {"deckType": 2, "userId": 7, "saved": True},
            "suits": [{"position": 1, "memberId": 211, "costumeId": 202113101, "viewStatus": 1, "suitSource": "deck",
                       "attachKey": "c1"},
                      {"position": 2, "memberId": 209, "costumeId": 302092002, "viewStatus": 2, "suitSource": "pinned",
                       "attachKey": ""}]})
        # No player state is a new player on the client's first tab (Customize).
        self.assertEqual(suits.provenance(None, []), {"deck": {"deckType": 2, "userId": None, "saved": False}, "suits": []})

    def test_costume_view_label_keeps_the_global_view_word_untranslated(self):
        # The global /api/i18n table also serves the texture tools, whose "View" menu falls
        # back to its own words (보기 / 表示) only while the global table has no "View".
        from webtools import i18n
        for language, label in (("ko", "뷰 상태"), ("ja", "ビュー状態")):
            with self.subTest(language=language):
                self.assertIsNone(i18n._TABLES[language].get("View"))
                self.assertEqual(i18n._TABLES[language].get("View status"), label)


class UserDatabaseTests(unittest.TestCase):
    def test_reads_one_players_mv_state_read_only(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            with closing(sqlite3.connect(root / "userdata.db")) as db, db:
                columns = ", ".join(f"member_master_id_{n} TEXT, suit_master_id_{n} TEXT" for n in range(1, 13))
                db.executescript(f"""
                    CREATE TABLE u_status (user_id INTEGER PRIMARY KEY, name TEXT);
                    CREATE TABLE u_member (user_id INTEGER, member_master_id INTEGER, suit_master_id INTEGER, view_status INTEGER);
                    CREATE TABLE u_suit (user_id INTEGER, suit_master_id INTEGER);
                    CREATE TABLE u_live_mv_deck (user_id INTEGER, live_master_id INTEGER, {columns});
                    CREATE TABLE u_live_mv_deck_custom (user_id INTEGER, live_master_id INTEGER, {columns});
                    INSERT INTO u_status VALUES (7, '{json.dumps({"dot_under_text": "Ayumu fan"})}'), (8, 'Other');
                    INSERT INTO u_member VALUES (7, 209, 102091001, 2), (8, 209, 102091001, 1);
                    INSERT INTO u_suit VALUES (7, 102111001), (8, 102112001);
                """)
                db.execute("INSERT INTO u_live_mv_deck_custom (user_id, live_master_id, member_master_id_1, suit_master_id_1, "
                           "member_master_id_2, suit_master_id_2) VALUES (7, 12035, '211', '102111001', 'null', NULL)")
            self.assertEqual(suits.users(root), [{"id": 7, "name": "Ayumu fan"}, {"id": 8, "name": "Other"}])
            state = suits.read_user(root, 7, 12035, suits.DECK_CUSTOM)
            self.assertEqual(state["custom"]["members"][:3], [211, None, None])
            self.assertEqual(state["custom"]["suits"][:2], [102111001, None])
            self.assertNotIn("original", state)
            self.assertEqual((state["ownedSuits"], state["members"]), (frozenset({102111001}), {209: {"viewStatus": 2}}))
            with self.assertRaisesRegex(ValueError, "does not exist"):
                suits.read_user(root, 9, 12035)
        with tempfile.TemporaryDirectory() as name:
            self.assertEqual(suits.users(name), [])
            with self.assertRaisesRegex(ValueError, "no Elichika player database"):
                suits.read_user(name, 7, 12035)


def _object(kind, path_id, file, tree=None, name=None):
    return SimpleNamespace(type=SimpleNamespace(name=kind), path_id=path_id, assets_file=file, tree=tree or {},
                           read=lambda: SimpleNamespace(m_ClassName=name))


class SuitAttachTests(unittest.TestCase):
    """CommonCoreMember.ApplyAttachData with MemberAttachTable.GetObject(attach key)."""

    def setUp(self):
        model_file = SimpleNamespace(name="CAB-model", externals=[SimpleNamespace(path="archive:/CAB-shader/CAB-shader"),
                                                                  SimpleNamespace(path="archive:/CAB-attach/CAB-attach")])
        attach_file = SimpleNamespace(name="CAB-attach", externals=[])
        self.script = _object("MonoScript", 1, model_file, name="BodyPartManager")
        self.body_c1 = _object("Texture2D", 31, attach_file)
        self.head_material = _object("Material", 32, attach_file, {"m_Name": "costume_head_copy"})
        self.table = _object("MonoBehaviour", 30, attach_file, {"m_Name": "costume_attach_materialcolor", "datas": [
            {"attachName": "c2", "attachType": 1, "replaceObjects": []},
            {"attachName": "c1", "attachType": 1, "replaceObjects": [
                {"replaceBindName": "costume_body", "replaceObject": {"m_FileID": 0, "m_PathID": 31}},
                {"replaceBindName": "costume_head", "replaceObject": {"m_FileID": 0, "m_PathID": 32}},
                {"replaceBindName": "costume_body", "replaceObject": {"m_FileID": 0, "m_PathID": 32}}]}]})
        self.parts = _object("MonoBehaviour", 2, model_file, {"m_Script": {"m_PathID": 1},
                                                              "attachTable": {"m_FileID": 2, "m_PathID": 30}})
        self.body = _object("Material", 3, model_file, {"m_Name": "costume_body", "m_SavedProperties": {"m_TexEnvs": [
            ("_RimlightTex", {"m_Texture": {"m_FileID": 0, "m_PathID": 9}}),
            ("_MainTex", {"m_Texture": {"m_FileID": 0, "m_PathID": 8}, "m_Scale": {"x": 1, "y": 1}})]}})
        by_id = {obj.path_id: obj for obj in (self.script, self.body_c1, self.head_material, self.table, self.parts, self.body)}
        self.scene = SimpleNamespace(env=SimpleNamespace(objects=list(by_id.values())), tree=lambda obj: obj.tree,
                                     warnings=[], warn=lambda code, name="": self.scene.warnings.append((code, name)))
        patcher = patch("webtools.core.model_viewer._ref",
                        side_effect=lambda owner, pointer: by_id.get((pointer or {}).get("m_PathID")))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_material_color_entry_replaces_main_texture_or_material(self):
        member = attach.MemberAttach.read(self.scene, "c1")
        self.assertEqual(member.describe()["objects"], {"costume_body": "Texture2D", "costume_head": "Material"})
        obj, tree = member.material(self.scene, self.body, self.body.tree)
        self.assertIs(obj, self.body)
        envs = dict(tree["m_SavedProperties"]["m_TexEnvs"])
        # The model file reaches the attach CAB through its second external (m_FileID 2).
        self.assertEqual(envs["_MainTex"], {"m_Texture": {"m_FileID": 2, "m_PathID": 31}, "m_Scale": {"x": 1, "y": 1}})
        self.assertEqual(envs["_RimlightTex"]["m_Texture"]["m_PathID"], 9)
        self.assertEqual(dict(self.body.tree["m_SavedProperties"]["m_TexEnvs"])["_MainTex"]["m_Texture"]["m_PathID"], 8,
                         "the cached source typetree is not modified")
        head = _object("Material", 4, self.body.assets_file, {"m_Name": "costume_head"})
        self.assertEqual(member.material(self.scene, head, head.tree), (self.head_material, self.head_material.tree))
        other = _object("Material", 5, self.body.assets_file, {"m_Name": "shadow"})
        self.assertEqual(member.material(self.scene, other, other.tree), (other, other.tree))

    def test_no_key_no_entry_or_another_type_changes_nothing(self):
        self.assertIsNone(attach.MemberAttach.read(self.scene, ""))
        self.assertIsNone(attach.MemberAttach.read(self.scene, "c3"))
        self.assertIsNone(attach.MemberAttach.read(self.scene, "c2"), "an entry without objects replaces nothing")
        self.table.tree["datas"][1]["attachType"] = 0
        self.assertIsNone(attach.MemberAttach.read(self.scene, "c1"), "only MemberAttachType.MaterialColor is applied")
        self.parts.tree["attachTable"] = {"m_FileID": 0, "m_PathID": 0}
        self.assertIsNone(attach.MemberAttach.read(self.scene, "c1"))


if __name__ == "__main__":
    unittest.main()
