"""Explicit native-asset and runtime member ID boundaries.

Mia/Lanzhu's original Unity/dictionary suffix order differs from m_member.
UI/API, verified game receipts and editor metadata use runtime IDs; legacy
modinstall chara_id and native asset names use the original suffix IDs.
These pure mappings do not validate or infer a member from arbitrary input.
"""


def member_from_native(value):
    return 423 - value if type(value) is int and value in (211, 212) else value


def native_from_member(value):
    return 423 - value if type(value) is int and value in (211, 212) else value
