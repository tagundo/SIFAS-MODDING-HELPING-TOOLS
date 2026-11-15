"""Unity header classification for separately source-bound preview inputs.

NoTarget is an editor's unassigned build target, not evidence of Android/iOS.
Accepting it for a preview/costume edit never changes a bundle's header, texture
codec or game-package platform. Game installers retain their native checks.
"""
from pathlib import Path

NO_TARGET = -2
ANDROID = 13
IOS = 9
SUPPORTED = {NO_TARGET, ANDROID, IOS}
LABELS = {NO_TARGET: "NoTarget / unassigned (-2)", ANDROID: "Android (13)", IOS: "iOS (9)"}


def filename(value):
    return " ".join(Path(str(value)).name.split())[:256] or "model"


def label(value):
    return LABELS.get(value, f"unsupported Unity build target ({value})")


def single_platform(values, name):
    """Return the actual declared header; never invent a native platform."""
    try:
        codes = {int(value) for value in values}
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"Cannot read the Unity platform for '{filename(name)}'. Reopen the original bundle.") from None
    if len(codes) != 1:
        detail = ", ".join(label(value) for value in sorted(codes)) or "no serialized assets"
        raise ValueError(f"'{filename(name)}' has ambiguous Unity platforms: {detail}. Open one original costume bundle; no platform conversion was attempted.")
    code = next(iter(codes))
    if code not in SUPPORTED:
        raise ValueError(f"'{filename(name)}' uses {label(code)}. This preview operation supports Android, iOS or an unassigned NoTarget header; use the matching original bundle.")
    return code


def from_environment(environment, name):
    return single_platform((getattr(asset, "target_platform", None) for asset in environment.assets), name)


def compatible(first, second):
    return first in SUPPORTED and second in SUPPORTED and (first == second or NO_TARGET in (first, second))


def require_compatible(wearer, other, *, wearer_name, other_name, role):
    if not compatible(wearer, other):
        raise ValueError(
            f"The {role} and wearer need matching Unity platforms: wearer '{filename(wearer_name)}' is {label(wearer)}, "
            f"but {role} '{filename(other_name)}' is {label(other)}. Load the {label(wearer)} original {role} "
            "or reopen this costume with its matching files. No incompatible result was published.")
