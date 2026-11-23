"""Who performs a 3D MV in which suit, following the client's MV path.

GL 3.12.0 libil2cpp (global-metadata v24.1), LiveMvDeckSelectDM.GetLiveMember3DAssetVOs
-> Live3DDM.GetMvLiveMember3DAssetVOs (0x2626ecc, lambda <>c__DisplayClass4_0.b__1
at 0x2629608) with the deck type the deck-select screen passes:

* Deck type. LiveMvDeckSelectDM.GetTabVOs (0x25ef21c) builds the tabs
  [Custom (2), Original (1)] for a 3D live (one null-type tab for a movie live), and
  LiveMvDeckTabGroup starts at tab index 0, so a player who never switched tabs
  plays the Custom deck. The CI account confirmed it: its deck-select cell was a
  DeckMemberCustomVO wearing 102111001 (m_member_init) for 12035, not the mapping's
  102112001.
* Members by position, LiveMvDM.GetMemberMasterIdByPos (0x2681828):
  m_live_member_mapping rows Concat m_live_override_member_mapping rows (member ??
  member_non_playable). Original: those positions. Custom: the saved custom deck's
  member_master_id_N (N = 1..count of mapping members); an empty slot takes the next
  mapping member, in position order, that the deck does not already hold.
* Suits by position, LiveMvDM.GetSuitMasterIdByPos (0x268285c):
  - Original (b__7): the original deck's suit worn by that member
    (SuitMaster.Get(suit).member_m_id), else the mapping/override suit if the user
    owns it (UserModel.UserSuitBySuitId), else m_member_init.suit_m_id, else the first
    m_suit_non_playable row of that member.
  - Custom (b__12): the custom deck suit at that position if it belongs to the member,
    else any custom deck slot's suit of that member, else m_member_init.suit_m_id, else
    the first m_suit_non_playable row. The mapping suit is never used.
* Model (b__1): m_suit.model_asset_path, else m_suit_non_playable.model_asset_path;
  m_suit_view(suit, u_member.view_status).model_asset_path replaces it when the user
  has that member and the row exists, and only then is the view status the user's
  (otherwise 1). Facial overrides are looked up by (member, that view status). The
  attach key is m_suit_attach.attach_key or "" (see mv_studio_suit_attach).

m_live_difficulty_override_member_mapping is not on this path: its readers are the
gameplay Live3DDM.GetSortedMembers / GetLiveSuitIds (with the player's live deck)
and Live3DDM.GetLiveMvDeckSuitIds, which has no caller. u_member.suit_master_id is
also only read by the gameplay GetLiveSuitIds; the MV path reads m_member_init.

Without a player database the editor resolves like a new Elichika player: no saved
MV decks, every m_suit owned (Elichika's account creation inserts all of m_suit into
u_suit) and view status 1.
"""

from contextlib import closing
import json
from pathlib import Path
import sqlite3

from .game_motions import _rows

DECK_ORIGINAL, DECK_CUSTOM = 1, 2
DEFAULT_DECK = DECK_CUSTOM
VIEW_DEFAULT = 1
SLOTS = 12  # UserLiveMvDeck member_master_id_1..12 / suit_master_id_1..12
USER_DATABASE = "userdata.db"


def _int(value):
    return value if type(value) is int and 0 < value < 1 << 31 else None


def mapping(master, mapping_id):
    """m_live_member_mapping then m_live_override_member_mapping rows, as the client concatenates them."""
    rows = []
    for position, member, center, suit in _rows(master, "SELECT position,member_master_id,is_center,suit_master_id "
                                                       "FROM m_live_member_mapping WHERE mapping_id=? ORDER BY rowid",
                                                (mapping_id,)):
        rows.append({"position": position, "member": member, "isCenter": bool(center), "suit": suit,
                     "nonPlayable": False})
    for position, member, other, center, suit, other_suit in _rows(
            master, "SELECT position,member_master_id,member_non_playable_master_id,is_center,suit_master_id,"
                    "suit_non_playable_master_id FROM m_live_override_member_mapping WHERE mapping_id=? ORDER BY rowid",
            (mapping_id,)):
        rows.append({"position": position, "member": member if member is not None else other,
                     "isCenter": bool(center), "suit": suit if suit is not None else other_suit,
                     "nonPlayable": member is None})
    return [row for row in rows if type(row["position"]) is int and 1 <= row["position"] <= 64
            and _int(row["member"])]


def _deck(deck, name):
    value = (deck or {}).get(name)
    if not isinstance(value, dict):
        return None
    members, suits = value.get("members") or [], value.get("suits") or []
    return {"members": [_int(item) for item in list(members)[:SLOTS]] + [None] * (SLOTS - min(SLOTS, len(members))),
            "suits": [_int(item) for item in list(suits)[:SLOTS]] + [None] * (SLOTS - min(SLOTS, len(suits)))}


def members_by_position(rows, deck_type, deck=None):
    """{position: mapping row (with the performing member)}, GetMemberMasterIdByPos."""
    ordered = {}
    for row in rows:
        ordered.setdefault(row["position"], row)
    if deck_type != DECK_CUSTOM:
        return ordered
    # Without a saved custom deck every slot is empty: the mapping members in position
    # order fill slots 1..n (the same positions for every GL mapping, which are 1..n).
    saved = _deck(deck, "custom") or {"members": [None] * SLOTS, "suits": [None] * SLOTS}
    members = [row for _, row in sorted(ordered.items())]
    slots = saved["members"][:len(members)]
    remaining = [row for row in members if row["member"] not in slots]
    result = {}
    for index, member in enumerate(slots):
        position = index + 1
        if member is not None:
            base = ordered.get(position) or {"position": position, "isCenter": False, "suit": None}
            result[position] = {**base, "position": position, "member": member, "nonPlayable": False,
                                "suit": None, "isCenter": base.get("isCenter", False)}
        elif remaining:
            row = remaining.pop(0)
            center = (ordered.get(position) or {}).get("isCenter", False)
            result[position] = {**row, "position": position, "isCenter": center}
    return result


class _Master:
    def __init__(self, master):
        self.master, self.suit_members, self.init, self.non_playable = master, {}, {}, {}

    def suit_member(self, suit):
        if suit not in self.suit_members:
            found = _rows(self.master, "SELECT member_m_id FROM m_suit WHERE id=?", (suit,))
            self.suit_members[suit] = found[0][0] if found else None
        return self.suit_members[suit]

    def member_init(self, member):
        if member not in self.init:
            found = _rows(self.master, "SELECT suit_m_id FROM m_member_init WHERE member_m_id=?", (member,))
            self.init[member] = found[0][0] if found else None
        return self.init[member]

    def first_non_playable(self, member):
        # SuitNonPlayableMaster.Select("WHERE member_m_id = ?").First(): table (rowid = id) order.
        if member not in self.non_playable:
            found = _rows(self.master, "SELECT id FROM m_suit_non_playable WHERE member_m_id=? ORDER BY rowid LIMIT 1",
                          (member,))
            self.non_playable[member] = found[0][0] if found else None
        return self.non_playable[member]


def suit_for(master, row, deck_type, deck=None, cache=None):
    """(suit id, source) for one performer, GetSuitMasterIdByPos."""
    cache = cache or _Master(master)
    member, position = row["member"], row["position"]
    if deck_type == DECK_CUSTOM:
        saved = _deck(deck, "custom")
        if saved is not None:
            suits = saved["suits"]
            at = suits[position - 1] if 1 <= position <= SLOTS else None
            if at is not None and cache.suit_member(at) == member:
                return at, "deck"
            for suit in suits:
                if suit is not None and cache.suit_member(suit) == member:
                    return suit, "deck"
    else:
        saved = _deck(deck, "original")
        if saved is not None:
            for suit in saved["suits"]:
                if suit is not None and cache.suit_member(suit) == member:
                    return suit, "deck"
        owned = (deck or {}).get("ownedSuits")
        mapped = _int(row.get("suit"))
        # A new Elichika player owns exactly the m_suit rows (subsystem/user_account).
        if mapped is not None and (mapped in owned if owned is not None else cache.suit_member(mapped) is not None):
            return mapped, "mapping"
    initial = cache.member_init(member)
    if _int(initial):
        return initial, "memberInit"
    other = cache.first_non_playable(member)
    if _int(other):
        return other, "nonPlayable"
    # The client would throw here (Enumerable.First on no rows). Keep the mapping suit.
    return _int(row.get("suit")), "mapping"


def view_status(deck, member):
    value = ((deck or {}).get("members") or {}).get(member)
    status = value.get("viewStatus") if isinstance(value, dict) else None
    return status if type(status) is int and 0 < status < 64 else None


def costume(master, suit, user_view=None):
    """(model asset path, effective view status) for a suit, GetMvLiveMember3DAssetVOs b__1."""
    found = _rows(master, "SELECT model_asset_path FROM m_suit WHERE id=?", (suit,))
    if not found or not found[0][0]:
        found = _rows(master, "SELECT model_asset_path FROM m_suit_non_playable WHERE id=?", (suit,))
    model = found[0][0] if found else None
    if user_view is not None:
        view = _rows(master, "SELECT model_asset_path FROM m_suit_view WHERE suit_master_id=? AND view_status=?",
                     (suit, user_view))
        if view and view[0][0]:
            return view[0][0], user_view
    return model, VIEW_DEFAULT


def attach_key(master, suit):
    found = _rows(master, "SELECT attach_key FROM m_suit_attach WHERE suit_master_id=?", (suit,))
    return str(found[0][0]) if found and found[0][0] else ""


def views(master, suit):
    return [status for status, model in _rows(master, "SELECT view_status,model_asset_path FROM m_suit_view "
                                                      "WHERE suit_master_id=? ORDER BY view_status", (suit,)) if model]


def normalize_deck(value):
    """Validate the optional player state a request or an Elichika route supplies."""
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) - {"deckType", "original", "custom", "ownedSuits", "members", "userId"}:
        raise ValueError("Choose a valid MV deck.")
    deck_type = value.get("deckType", DEFAULT_DECK)
    if deck_type not in (DECK_ORIGINAL, DECK_CUSTOM):
        raise ValueError("Choose the Customize or Original MV deck.")
    result = {"deckType": deck_type}
    for name in ("original", "custom"):
        saved = value.get(name)
        if saved is None:
            continue
        if (not isinstance(saved, dict) or set(saved) - {"members", "suits"} or
                any(not isinstance(saved.get(field, []), list) or len(saved.get(field, [])) > SLOTS or
                    any(item is not None and _int(item) is None for item in saved.get(field, []))
                    for field in ("members", "suits"))):
            raise ValueError("Choose a valid MV deck.")
        result[name] = {"members": list(saved.get("members", [])), "suits": list(saved.get("suits", []))}
    owned = value.get("ownedSuits")
    if owned is not None:
        if not isinstance(owned, list) or len(owned) > 100000 or any(_int(item) is None for item in owned):
            raise ValueError("Choose valid owned suits.")
        result["ownedSuits"] = frozenset(owned)
    members = value.get("members")
    if members is not None:
        if not isinstance(members, dict) or len(members) > 1024:
            raise ValueError("Choose valid member states.")
        result["members"] = {}
        for member, state in members.items():
            member = int(member) if isinstance(member, str) and member.isdigit() else member
            status = state.get("viewStatus") if isinstance(state, dict) else None
            if _int(member) is None or not isinstance(state, dict) or set(state) - {"viewStatus", "suitMasterId"} or \
                    type(status) is not int or not 0 < status < 64:
                raise ValueError("Choose valid member states.")
            result["members"][member] = {"viewStatus": status}
    if "userId" in value:
        if _int(value["userId"]) is None:
            raise ValueError("Choose a valid player.")
        result["userId"] = value["userId"]
    return result


def _cells(row, field):
    values = []
    for index in range(1, SLOTS + 1):
        raw = row.get(f"{field}_{index}")
        try:
            value = json.loads(raw) if isinstance(raw, str) else raw
        except ValueError:
            value = None
        values.append(_int(value))
    return values


def read_user(root, user_id, live_id, deck_type=DEFAULT_DECK):
    """Read one Elichika player's MV state read-only from <root>/userdata.db.

    u_live_mv_deck / u_live_mv_deck_custom (the saved Original / Custom decks), u_suit
    (owned suits, the Original deck's mapping filter) and u_member.view_status."""
    if _int(user_id) is None or _int(live_id) is None:
        raise ValueError("Choose a valid player and MV.")
    path = Path(root).resolve() / USER_DATABASE
    if not path.is_file():
        raise ValueError("This app has no Elichika player database.")
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        if not _rows(db, "SELECT 1 FROM u_status WHERE user_id=?", (user_id,)):
            raise ValueError("The selected player does not exist.")
        result = {"deckType": deck_type, "userId": user_id}
        for name, table in (("original", "u_live_mv_deck"), ("custom", "u_live_mv_deck_custom")):
            found = _rows(db, f"SELECT * FROM {table} WHERE user_id=? AND live_master_id=?", (user_id, live_id))
            if found:
                row = dict(found[0])
                result[name] = {"members": _cells(row, "member_master_id"), "suits": _cells(row, "suit_master_id")}
        result["ownedSuits"] = frozenset(suit for suit, in _rows(db, "SELECT suit_master_id FROM u_suit WHERE user_id=?",
                                                                    (user_id,)) if _int(suit))
        result["members"] = {member: {"viewStatus": status} for member, status in _rows(
            db, "SELECT member_master_id,view_status FROM u_member WHERE user_id=?", (user_id,))
            if _int(member) and type(status) is int and 0 < status < 64}
    return result


def users(root):
    """[{id, name}] of the local Elichika player database, or [] when there is none."""
    path = Path(root).resolve() / USER_DATABASE
    if not path.is_file():
        return []
    try:
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
            rows = _rows(db, "SELECT user_id,name FROM u_status ORDER BY user_id LIMIT 64")
    except sqlite3.Error:
        return []
    result = []
    for user, name in rows:
        if _int(user) is None:
            continue
        try:
            text = json.loads(name).get("dot_under_text") if isinstance(name, str) and name.startswith("{") else name
        except (ValueError, AttributeError):
            text = name
        result.append({"id": user, "name": str(text or user)[:60]})
    return result
