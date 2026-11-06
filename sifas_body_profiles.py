"""Shared body-profile data for the mesh tool and the rigged viewer.

This module deliberately has no Unity, desktop UI or web dependencies. A
transition is a per-axis multiplier from an explicitly chosen source type;
opening a costume never establishes that its current type is ``default``.
"""


THIGH_STATES = {
    "slim": (1.0, 0.941748, 0.932695),
    "default": (1.0, 1.0, 1.0),
    "thick": (1.0, 1.03884, 1.0577),
}
THIGH_BONES = ("LeftUpLeg", "RightUpLeg")
THIGH_TRANSITIONS = [("slim", "default"), ("slim", "thick"),
                     ("default", "slim"), ("default", "thick"),
                     ("thick", "slim"), ("thick", "default")]
_THIGH_LABELS = {"slim": "Slim", "default": "Standard", "thick": "Thick"}


def thigh_factor(src, dst):
    """Return the existing tool's exact destination/source XYZ multiplier."""
    return tuple(b / a for a, b in zip(THIGH_STATES[src], THIGH_STATES[dst]))


def thigh_profile_metadata():
    """Return fresh, JSON-safe profiles without guessing a source body type."""
    return {
        "presets": [{"id": f"{src}:{dst}", "sourceState": src,
                     "targetState": dst, "sourceLabel": _THIGH_LABELS[src],
                     "targetLabel": _THIGH_LABELS[dst],
                     "scaleDelta": list(thigh_factor(src, dst))}
                    for src, dst in THIGH_TRANSITIONS],
        "presetApplication": "relative_to_original_static_scale",
        "presetMeaning": "explicit_source_to_target_body_type",
        "presetPercentagePolicy": "replace_same_axes",
        "presetSourceRequired": True,
        "presetSource": "sifas_body_profiles.py:THIGH_STATES/thigh_factor",
    }
