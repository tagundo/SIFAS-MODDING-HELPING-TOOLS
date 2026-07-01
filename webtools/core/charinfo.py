"""Reference body data per character, for the "Character Body Info" tool.

Sources:
  * NAMES / IDs           - the SIFAS character roster.
  * SKIN_TONE             - the official skin-tone class each character uses,
                            from skin_tone_changer.py's documented grouping.
  * JIGGLE                - the breast-physics (dyna) tier, from
                            sifas_breast_tuner.CHAR_ID_TO_N_MAPPING.
  * BODY                  - LiveCoreMemberNodeScaling values (height / breasts /
                            head / hips / ribbon). These are COSTUME-specific:
                            the numbers below are the Summer Splash 2020 costume
                            (for Mia and Lanzhu, the Fest 3rd UR outfit), which is
                            the commonly-cited reference set. The Breasts column
                            matches the canonical per-character sizes used by the
                            breast tuner presets. A value of None means "not
                            scaled" (left at the default 1.0) for that costume.
"""

NAMES = {
    1: "Honoka Kousaka", 2: "Eli Ayase", 3: "Kotori Minami", 4: "Umi Sonoda",
    5: "Rin Hoshizora", 6: "Maki Nishikino", 7: "Nozomi Tojo", 8: "Hanayo Koizumi",
    9: "Nico Yazawa",
    101: "Chika Takami", 102: "Riko Sakurauchi", 103: "Kanan Matsuura",
    104: "Dia Kurosawa", 105: "You Watanabe", 106: "Yoshiko Tsushima",
    107: "Hanamaru Kunikida", 108: "Mari Ohara", 109: "Ruby Kurosawa",
    201: "Ayumu Uehara", 202: "Kasumi Nakasu", 203: "Shizuku Osaka",
    204: "Karin Asaka", 205: "Ai Miyashita", 206: "Kanata Konoe",
    207: "Setsuna Yuki", 208: "Emma Verde", 209: "Rina Tennoji",
    210: "Shioriko Mifune", 211: "Mia Taylor", 212: "Lanzhu Zhong",
}

ALL_IDS = sorted(NAMES)

# Official skin-tone class (see skin_tone_changer.py header). Subunit groupings
# there are expanded to members: Printemps = Honoka/Kotori/Hanayo, CYaRon =
# Chika/You/Ruby, Guilty Kiss = Riko/Yoshiko/Mari, A-ZU-NA = Ayumu/Setsuna/Shizuku.
SKIN_TONE = {
    1: "default", 2: "bright", 3: "default", 4: "default", 5: "medium_tone",
    6: "default", 7: "slight", 8: "default", 9: "bright",
    101: "default", 102: "bright", 103: "default", 104: "bright", 105: "default",
    106: "bright", 107: "default", 108: "bright", 109: "default",
    201: "bright", 202: "default", 203: "bright", 204: "default", 205: "bright",
    206: "default", 207: "bright", 208: "bright", 209: "default",
    210: "bright", 211: "bright", 212: "slight",
}

# Breast-physics (dyna) tier per character, inverted from
# sifas_breast_tuner.CHAR_ID_TO_N_MAPPING (higher n = looser jiggle).
_JIGGLE_GROUPS = {
    0: [9, 209], 1: [5], 2: [4, 109, 202], 3: [1, 6, 106, 210],
    4: [3, 102, 104, 203, 212], 5: [8, 101, 105, 201, 207],
    6: [2, 103, 107, 108, 205, 206, 211], 7: [7, 204, 208],
}
JIGGLE = {cid: n for n, ids in _JIGGLE_GROUPS.items() for cid in ids}

# [Thigh Scale] per-character thigh body type (LeftUpLeg/RightUpLeg), from
# sifas_mesh_baker.THIGH_STATES. X stays 1.0 (leg length); Y/Z are the thickness.
THIGH_STATES = {
    "slim":    (1.0, 0.941748, 0.932695),
    "default": (1.0, 1.0, 1.0),
    "thick":   (1.0, 1.03884, 1.0577),
}
_THIGH_SLIM = {9, 109, 209, 212}    # Nico, Ruby, Rina, Lanzhu
_THIGH_THICK = {7, 108, 204, 208}   # Nozomi, Mari, Karin, Emma
THIGH = {cid: ("slim" if cid in _THIGH_SLIM
               else "thick" if cid in _THIGH_THICK else "default")
         for cid in NAMES}

# (height, breasts, head, hips, ribbon); each is (x, y, z) or None if unscaled.
BODY = {
    1:   ((0.985, 0.985, 0.985), (0.9, 0.98, 0.96),  (1.015, 1.015, 1.015), None, None),
    2:   ((1.022, 1.022, 1.022), (1.16, 1.08, 1.16), (0.979, 0.979, 0.979), None, None),
    3:   (None, None, None, None, None),
    4:   (None, (0.8, 0.96, 0.92), None, None, None),
    5:   ((0.971, 0.971, 0.971), (0.72, 0.95, 0.9),  (1.03, 1.03, 1.03),   None, None),
    6:   ((1.015, 1.015, 1.015), (0.9, 0.98, 0.96),  (0.986, 0.986, 0.986), None, None),
    7:   (None, (1.3, 1.15, 1.3), None, (1.0, 1.03, 1.03), None),
    8:   ((0.98, 0.98, 0.98),    (1.08, 1.04, 1.08), (1.023, 1.023, 1.023), None, None),
    9:   ((0.963, 0.963, 0.963), (0.64, 0.94, 0.88), (1.038, 1.038, 1.038), (1.0, 0.95, 0.95), (1.276868, 1.2, 1.2)),
    101: ((0.985, 0.985, 0.985), (1.04, 1.02, 1.04), (1.015, 1.015, 1.015), None, None),
    102: ((1.007, 1.007, 1.007), None,               (0.993, 0.993, 0.993), None, None),
    103: ((1.022, 1.022, 1.022), (1.16, 1.08, 1.16), (0.979, 0.979, 0.979), None, None),
    104: ((1.022, 1.022, 1.022), None,               (0.979, 0.979, 0.979), None, None),
    105: ((0.985, 0.985, 0.985), (1.04, 1.02, 1.04), (1.015, 1.015, 1.015), None, None),
    106: ((0.98, 0.98, 0.98),    (0.95, 0.99, 0.98), (1.023, 1.023, 1.023), None, None),
    107: ((0.949, 0.949, 0.949), (1.12, 1.06, 1.12), (1.054, 1.054, 1.054), None, None),
    108: ((1.029, 1.029, 1.029), (1.2, 1.1, 1.2),    (0.972, 0.972, 0.972), (1.0, 1.03, 1.03), None),
    109: ((0.963, 0.963, 0.963), (0.8, 0.96, 0.92),  (1.038, 1.038, 1.038), (1.0, 0.95, 0.95), None),
    201: (None, (1.04, 1.02, 1.04), None, None, None),
    202: ((0.971, 0.971, 0.971), (0.8, 0.96, 0.92),  (1.03, 1.03, 1.03),   None, (1.091071, 1.133674, 1.087181)),
    203: ((0.985, 0.985, 0.985), None,               (0.985, 0.985, 0.985), None, None),
    204: ((1.059, 1.059, 1.059), (1.22, 1.11, 1.22), (0.942, 0.942, 0.942), None, None),
    205: ((1.029, 1.029, 1.029), (1.12, 1.06, 1.12), (0.972, 0.972, 0.972), None, None),
    206: ((0.993, 0.993, 0.993), (1.16, 1.08, 1.16), (1.008, 1.008, 1.008), None, None),
    207: ((0.963, 0.963, 0.963), (1.08, 1.04, 1.08), (1.038, 1.038, 1.038), None, None),
    208: ((1.051, 1.051, 1.051), (1.3, 1.18, 1.3),   (0.95, 0.95, 0.95),   (1.0, 1.03, 1.03), None),
    209: ((0.927, 0.927, 0.927), (0.61, 0.91, 0.85), (1.077, 1.077, 1.077), (1.0, 0.95, 0.95), None),
    210: ((1.007, 1.007, 1.007), (0.95, 0.99, 0.98), (0.993, 0.993, 0.993), None, None),
    211: ((0.98, 0.98, 0.98),    None,               (1.023, 1.023, 1.023), (1.0, 0.95, 0.95), None),
    212: ((1.044, 1.044, 1.044), (1.14, 1.07, 1.14), (0.958, 0.958, 0.958), None, None),
}


def _fmt_vec(v):
    if v is None:
        return "— (default 1.0)"
    x, y, z = v
    if x == y == z:
        return f"{x:g} (uniform)"
    return f"{x:g} / {y:g} / {z:g}"


def describe(cid):
    """Formatted reference lines for one character id."""
    name = NAMES.get(cid, str(cid))
    height, breasts, head, hips, ribbon = BODY.get(cid, (None,) * 5)
    tier = JIGGLE.get(cid)
    breast_line = _fmt_vec(breasts)
    if breasts is not None and tier is not None:
        breast_line += f"   (jiggle tier {tier})"
    tclass = THIGH.get(cid, "default")
    thigh_line = ("default (standard)" if tclass == "default"
                  else f"{tclass}  ({_fmt_vec(THIGH_STATES[tclass])})")
    return [
        f"{name}  (ID {cid})",
        f"  Skin tone : {SKIN_TONE.get(cid, '?')}",
        f"  Breasts   : {breast_line}",
        f"  Thighs    : {thigh_line}",
        f"  Height    : {_fmt_vec(height)}",
        f"  Head      : {_fmt_vec(head)}",
        f"  Hips      : {_fmt_vec(hips)}",
        f"  Ribbon    : {_fmt_vec(ribbon)}",
    ]
