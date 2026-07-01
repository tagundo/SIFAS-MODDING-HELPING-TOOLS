"""Character Body Info — a reference tool (no file processing).

Prints per-character body data (ID, skin tone, breast size + jiggle tier, and the
height / head / hips / ribbon node scaling) to the job log, so a modder can look
up a character's stock values before editing a bundle.
"""
from webtools.core import charinfo


def run_charinfo(job, params):
    sel = (params.get("character") or "all").strip()
    if sel == "all":
        ids = charinfo.ALL_IDS
    elif sel.isdigit() and int(sel) in charinfo.NAMES:
        ids = [int(sel)]
    else:
        job.log("Unknown character.")
        return "no data"

    job.log("Body scaling = Summer Splash 2020 costume (Mia / Lanzhu: Fest 3rd UR).")
    job.log("Breasts x/y/z are the canonical per-character sizes; jiggle tier is the dyna tier.")
    job.log("")
    for i, cid in enumerate(ids):
        for line in charinfo.describe(cid):
            job.log(line)
        job.log("")
        if ids is charinfo.ALL_IDS:
            job.progress(i + 1, len(ids))
    return f"shown {len(ids)} character(s)"
