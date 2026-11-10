"""Existing Mod ZIP thumbnail replacement adapter; Selected files is shared."""
import json

from webtools.core import mod_thumbnail_replace, viewer_thumbnails


def run_thumbnail_replace(job, params):
    options = mod_thumbnail_replace.render_options(params)
    provider = viewer_thumbnails.updater_provider(params)
    path = options["in_path"]
    job.progress(0, 1)
    result = mod_thumbnail_replace.replace(path, options["out_dir"], provider(path),
        size=options["thumbnail_size"], variant=options["variant"], should_stop=job.should_stop)
    job.add_output(result["output_path"])
    job.log("THUMBNAIL_UPDATE " + json.dumps(result, ensure_ascii=False, sort_keys=True))
    job.progress(1, 1)
    return "created " + result["output_path"]
