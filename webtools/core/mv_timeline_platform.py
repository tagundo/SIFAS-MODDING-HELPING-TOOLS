"""MV timeline platform conversion ("MV 타임라인 플랫폼 변환"): an Android live timeline for iOS and back.

Modelled on the costume platform conversion: the SAME 3D asset's stock timeline for the output
platform is the template (read from the game catalog, downloaded when allowed), and the source
timeline's content is written into it with MV Studio's own native export
(``mv_studio_timeline.export_timeline``: the path "Apply all" uses to bake a project onto each
platform's stock). Nothing platform-specific is byte-patched: every object the editor does not
model (shaders, type trees, platform fields) is the output platform's own.

The result is checked before it is returned: it must parse to exactly the source's tracks,
clips and values. A source with content the native export cannot carry (a track layout or
values that differ from the asset's stock where the editor does not write them) is refused
instead of being converted with losses.

Also here: the stage-bound track count of a timeline (tracks that address objects of the MV's
stage), used to warn before a timeline goes into another MV slot without its stage, and
``check_editor_bytes``, the content check Elichika's pack install offers beyond its structural
validation.
"""
from contextlib import closing
from pathlib import Path
import time

from . import game_models as game
from . import mv_studio_register as register
from . import transient_failures

PLATFORMS = ("android", "ios")
REGIONS = ("gl", "jp")
# The timeline export format of this MV Studio: what its native export writes. An exported pack
# records it (Elichika's pack entry mvstudio.json), so a server whose MV Studio tools are older can
# say a pack was made by a newer MV Studio. Raise it whenever the export starts writing something it
# did not (a value in mv_studio_timeline._EDITABLE_VALUES, a track field in EXPORTABLE_TRACK_FIELDS,
# clip timing): tests/test_mv_crossslot.py pins that surface to this number.
# 2: track mutes, member targets (member positions, base light colour sources, depth-of-field focus),
# penlight motion and colours; in the same release, split-screen sub camera shot edits and resized
# camera shots with edits.
EXPORT_FORMAT = 2

PLATFORM = "Choose Android or iOS."
REGION = "Select the GL or JP catalog."
ASSET = "Enter the 3D asset ID of the MV this timeline belongs to."
SAME_PLATFORM = "The timeline is already for the output platform."
WRONG_PLATFORM = "The timeline is not for the chosen source platform."
NOT_TIMELINE = "This file is not a native live timeline."
NO_ASSET = "This 3D MV is not in the game catalog of this region."
NO_TEMPLATE = "The game catalog has no original timeline of this 3D MV for the output platform."
TEMPLATE_DOWNLOAD = ("The original timeline of this 3D MV for the output platform is not available locally. Allow the "
                     "download.")
NOT_THIS_ASSET = "The timeline does not belong to this 3D MV:"
LOSSY = "The converted timeline would differ from the source, so nothing was converted:"
# check_editor_bytes: a timeline it cannot confirm is not refused, it needs the user's consent.
VALUES_UNKNOWN = ("The timeline holds data this server's MV Studio tools do not write: the pack was made by a newer MV "
                  "Studio or changed elsewhere. Updating Elichika and its asset editing tools (modtools) lets this "
                  "server check it.")
VALUES_NEWER = ("The pack was made by a newer MV Studio: its timeline holds data this server's MV Studio tools do not "
                "write. Updating Elichika and its asset editing tools (modtools) lets this server check it.")
VALUES_UNCHECKED = ("The timeline's values could not be checked: the check ran out of time or memory, or the original "
                    "timeline was not available.")
MESSAGES = (PLATFORM, REGION, ASSET, SAME_PLATFORM, WRONG_PLATFORM, NOT_TIMELINE, NO_ASSET, NO_TEMPLATE,
            TEMPLATE_DOWNLOAD, NOT_THIS_ASSET, LOSSY, VALUES_UNKNOWN, VALUES_NEWER, VALUES_UNCHECKED)

_STAGE_ROOT = "/EntryPoint/Live/Stages/"


class ConversionError(ValueError):
    """A refused conversion; ``labels`` names the tracks concerned."""

    def __init__(self, message, labels=()):
        super().__init__(message)
        self.labels = list(labels)


class UncheckedValues(ValueError):
    """check_editor_bytes could not confirm a timeline as this MV Studio's own output. ``reason``:
    "values" (it holds data this MV Studio does not write), "newer" (the same, from a pack that says
    a newer MV Studio made it) or "unchecked" (the check itself could not run). Not a refusal: the
    caller asks the user before it installs such a timeline."""

    def __init__(self, message, reason):
        super().__init__(message)
        self.reason = reason


def stage_bound_tracks(tracks):
    """Labels of the tracks that drive objects of the MV's stage: the StageEffect group and every
    track bound under the stage root. Another stage may not have the objects they address."""
    labels = []
    for track in tracks or ():
        if not isinstance(track, dict) or track.get("nativeClass") == "GroupTrack":
            continue
        label, binding = str(track.get("label") or ""), str(track.get("binding") or "")
        if label.startswith("StageEffect/") or binding.startswith(_STAGE_ROOT):
            labels.append(label or str(track.get("id") or ""))
    return labels


def _check(platform, region, asset_id):
    if platform not in PLATFORMS:
        raise ValueError(PLATFORM)
    if region not in REGIONS:
        raise ValueError(REGION)
    if not register._identity(asset_id):
        raise ValueError(ASSET)


def template_descriptor(repo_root, region, asset_id, platform):
    """The catalog row of the asset's TRUE stock timeline for ``platform`` (None when not catalogued)."""
    _check(platform, region, asset_id)
    root = Path(repo_root).resolve()
    with closing(game._readonly(root / "assets/db" / region / "masterdata.db")) as master:
        row = master.execute("SELECT timeline FROM m_live_3d_asset WHERE id=?", (asset_id,)).fetchone()
        if row is None or not row[0]:
            raise ValueError(NO_ASSET)
        key = register._stock_key(master, asset_id, row[0])
    descriptor, _ = register._first_catalog_row(root, region, platform, "en", "live_timeline", key)
    return descriptor


def template_status(repo_root, region, asset_id, platform):
    """{"status": local | download | missing, "bytes"?}: whether the output platform's template is at hand."""
    descriptor = template_descriptor(repo_root, region, asset_id, platform)
    if descriptor is None:
        return {"status": "missing"}
    if register._load(repo_root, descriptor, download=False) is not None:
        return {"status": "local"}
    size = descriptor.get("pack_size") or descriptor.get("size")
    return {"status": "download", **({"bytes": size} if size else {})}


def template(repo_root, region, asset_id, platform, *, download=False, deadline=None):
    """The asset's stock timeline for ``platform`` (plaintext UnityFS bytes)."""
    descriptor = template_descriptor(repo_root, region, asset_id, platform)
    if descriptor is None:
        raise ValueError(NO_TEMPLATE)
    raw = register._load(repo_root, descriptor, download=False, deadline=deadline)
    if raw is None and download:
        raw = register._load(repo_root, descriptor, download=True, deadline=deadline)
    if raw is None:
        raise ValueError(TEMPLATE_DOWNLOAD)
    return raw


def _differing(source_tracks, output_tracks):
    labels = []
    for before, after in zip(source_tracks, output_tracks):
        if before != after:
            labels.append(register._label(before))
    if len(source_tracks) != len(output_tracks):
        labels.append("…")
    return sorted(dict.fromkeys(labels))


def convert_parsed(src_bytes, dst_template, *, name="timeline"):
    """Write ``src_bytes``'s content into ``dst_template`` (the same asset's stock of the output
    platform) and verify it. Returns the output bytes."""
    if not isinstance(src_bytes, bytes) or not src_bytes.startswith(b"UnityFS\0"):
        raise ValueError(NOT_TIMELINE)
    try:
        source = register._parse(src_bytes, "source")
    except ValueError as error:
        raise ValueError(NOT_TIMELINE) from error
    if not source.get("tracks"):
        raise ValueError(NOT_TIMELINE)
    reference = register._parse(dst_template, "template")
    try:
        normalized, _ = register.normalize(reference["tracks"], source["tracks"])
    except register.StructureError as error:
        raise ConversionError(NOT_THIS_ASSET, error.labels) from error
    # The source is timeline bytes, never a project an older MV Studio saved: no legacy camera step,
    # which could turn an edited camera point back to the template's rotation.
    output = register._export(dst_template, name, normalized, legacy_camera=False)
    converted = register._parse(output, "verify")["tracks"]
    if converted != source["tracks"]:
        raise ConversionError(LOSSY, _differing(source["tracks"], converted))
    return output


def check_editor_bytes(raw, template_bytes, *, pack_format=None):
    """Raise UncheckedValues unless ``raw`` is exactly what this MV Studio writes for its own content.

    ``template_bytes`` is the TRUE stock of the timeline's source MV for the same platform (None:
    not available). MV Studio's every output (Apply all, another slot, a pack, a conversion) is its
    parsed content exported onto that stock, so exporting ``raw``'s parsed content onto it again
    gives ``raw`` byte for byte. A timeline that holds data this MV Studio does not write does not:
    one from a newer MV Studio (a field this one does not export) or one changed elsewhere (a NaN
    curve key, an out-of-range index inside a clip it does not model). ``pack_format`` is the
    EXPORT_FORMAT the pack records for its MV Studio; above this one, the message says the pack
    is newer. The check runs on a timeline that already passed Elichika's structural validation (its
    install_pack ``check``); a mismatch is a question for the user, never a refusal.

    Only a structural refusal (a timeline this MV Studio cannot read, NOT_THIS_ASSET or LOSSY,
    StructureError) or different bytes mean "not what this MV Studio writes". A check that cannot
    run (no template, a time limit, memory or another failure of the machine, an unreadable template
    or an export error) raises reason "unchecked"."""
    newer = type(pack_format) is int and pack_format > EXPORT_FORMAT
    differs = UncheckedValues(VALUES_NEWER, "newer") if newer else UncheckedValues(VALUES_UNKNOWN, "values")
    unchecked = UncheckedValues(VALUES_UNCHECKED, "unchecked")
    if not isinstance(template_bytes, bytes):
        raise unchecked
    if not isinstance(raw, bytes) or not raw.startswith(b"UnityFS\0"):
        raise differs
    watch = transient_failures.Watch()  # a time budget or a machine failure noted while checking
    try:  # the timeline itself: a bundle this MV Studio cannot read (any data error) is not one it writes
        readable = bool(register._parse(raw, "source").get("tracks"))
    except (*transient_failures.ENVIRONMENT, RecursionError) as error:
        raise unchecked from error
    except Exception as error:  # noqa: BLE001 - UnityPy's EOFError, struct.error, KeyError... on damaged data
        raise (differs if watch.clean else unchecked) from error
    if not readable:
        raise differs
    try:
        again = convert_parsed(raw, template_bytes)
    except (ConversionError, register.StructureError) as error:
        raise (differs if watch.clean else unchecked) from error
    except Exception as error:  # noqa: BLE001 - the template, the export, a time limit, memory: not checked
        raise unchecked from error
    if again != raw:
        raise differs


def convert_timeline(src_bytes, src_platform, dst_platform, region, asset_id, *, root, download=False, name="timeline",
                     deadline=None, template_bytes=None):
    """``src_bytes`` (a ``src_platform`` timeline of 3D asset ``asset_id`` in ``region``) as a
    ``dst_platform`` timeline: the asset's own ``dst_platform`` stock with the source's content.
    ``template_bytes`` is that stock when the caller already has it (``template()``'s result, e.g.
    fetched once for both the conversion and a later check); else it is read here.

    Raises ValueError (SAME_PLATFORM, WRONG_PLATFORM, NO_TEMPLATE, TEMPLATE_DOWNLOAD, ...) or
    ConversionError (NOT_THIS_ASSET, LOSSY, with track labels)."""
    _check(src_platform, region, asset_id)
    if dst_platform not in PLATFORMS:
        raise ValueError(PLATFORM)
    if src_platform == dst_platform:
        raise ValueError(SAME_PLATFORM)
    if not isinstance(src_bytes, bytes) or not src_bytes.startswith(b"UnityFS\0"):
        raise ValueError(NOT_TIMELINE)
    found = register._blob_platform(src_bytes)
    if found is not None and found != src_platform:
        raise ValueError(WRONG_PLATFORM)
    if template_bytes is not None:
        return convert_parsed(src_bytes, template_bytes, name=name)
    deadline = deadline if deadline is not None else time.monotonic() + (240 if download else 60)
    raw = template(root, region, asset_id, dst_platform, download=download, deadline=deadline)
    return convert_parsed(src_bytes, raw, name=name)


def blob_platform(raw):
    """android, ios or None: the Unity build target of a native timeline."""
    return register._blob_platform(raw)


__all__ = ("convert_timeline", "convert_parsed", "template", "template_status", "template_descriptor",
           "stage_bound_tracks", "blob_platform", "check_editor_bytes", "ConversionError", "UncheckedValues",
           "EXPORT_FORMAT", "MESSAGES", "PLATFORMS")
