"""MV timeline platform conversion tool ("MV 타임라인 플랫폼 변환"), webtools/core/mv_timeline_platform.py.

A raw native timeline (.unity) is converted to the other platform with the same 3D asset's stock
timeline of that platform as the template (region + 3D asset id given). An MV timeline pack
(.sifasmv) names its region and asset itself: the platform it lacks is added, and a new pack with
both platforms is written.
"""
from pathlib import Path

from webtools.tools.common import single_out_path

DIRECTIONS = {"android_to_ios": ("android", "ios"), "ios_to_android": ("ios", "android")}
CHOOSE_DIRECTION = "Choose the conversion direction."
CHOOSE_SOURCE = "Choose a native MV timeline (.unity) or an MV timeline pack (.sifasmv)."
CHOOSE_OUTPUT = "Choose the output folder."
PACK_COMPLETE = "The pack already has Android and iOS timelines."
LEGACY_PACK = ("An old live timeline zip does not name the MV it was made from. Open it in MV Studio and export an MV "
               "timeline pack.")
MESSAGES = (CHOOSE_DIRECTION, CHOOSE_SOURCE, CHOOSE_OUTPUT, PACK_COMPLETE, LEGACY_PACK)


def _asset_id(value):
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if 0 < number < 1 << 31 else None


def run_mv_timeline_platform(job, params):
    from webtools.core import mv_timeline_platform as conversion
    direction = params.get("direction")
    if direction not in DIRECTIONS:
        raise ValueError(CHOOSE_DIRECTION)
    source_platform, platform = DIRECTIONS[direction]
    source = Path(str(params.get("source") or "")).expanduser()
    if not params.get("source") or not source.is_file():
        raise ValueError(CHOOSE_SOURCE)
    out_dir = params.get("out_dir")
    if not isinstance(out_dir, str) or not out_dir:
        raise ValueError(CHOOSE_OUTPUT)
    out_dir = Path(out_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    download = params.get("download_missing", False)
    if not isinstance(download, bool):
        raise ValueError("Choose whether to download the missing original timeline.")
    root = Path.cwd()
    job.progress(0, 1)
    if source.suffix.lower() == ".sifasmv":
        from webtools.core import mv_studio_pack
        pack = mv_studio_pack.read(source)
        manifest, files = pack["manifest"], dict(pack["platforms"])
        if pack["legacy"] or not isinstance(manifest.get("source"), dict):
            raise ValueError(LEGACY_PACK)
        if len(files) == 2:
            raise ValueError(PACK_COMPLETE)
        have = source_platform if source_platform in files else next(iter(files))
        want = "ios" if have == "android" else "android"
        origin = manifest.get("source") or {}
        job.log(f"Converting the pack's {have} timeline for {want} (3D {origin.get('assetId')}, "
                f"{str(origin.get('region')).upper()})")
        files[want] = conversion.convert_timeline(files[have], have, want, origin.get("region"), origin.get("assetId"),
                                                  root=root, download=download, name=source.stem)
        # The stage as write_pack needs it (all five fields) and the legacy layout's inputs.
        stage, completed = mv_studio_pack.rewrite_stage(root, manifest)
        if completed:
            job.log(f"The pack's stage leaves out {', '.join(completed)}: taken from the original stage of "
                    f"3D {origin.get('assetId')}")
        data = mv_studio_pack.module().write_pack(
            name=manifest.get("name") or source.stem, note=manifest.get("note") or "", song=manifest.get("song"),
            source=origin, target_asset_id=(manifest.get("target") or {}).get("assetId"), timelines=files,
            created=manifest.get("created"), **stage)
        output = Path(single_out_path(str(out_dir), str(source), "", "-android-ios"))
        output.write_bytes(bytes(data))
    else:
        region = params.get("region") or "gl"
        asset_id = _asset_id(params.get("asset_id"))
        if asset_id is None:
            raise ValueError(conversion.ASSET)
        job.log(f"Converting the {source_platform} timeline for {platform} with the original of 3D {asset_id} "
                f"({region.upper()})")
        result = conversion.convert_timeline(source.read_bytes(), source_platform, platform, region, asset_id,
                                             root=root, download=download, name=source.stem)
        suffix = params.get("suffix") or ("_iOS" if platform == "ios" else "_APK")
        output = Path(single_out_path(str(out_dir), str(source), "", suffix))
        output.write_bytes(result)
    job.add_output(output)
    job.progress(1, 1)
    return f"Converted: {output.name}"
