"""Character Body Info — a reference tool (no file processing).

"All characters" prints a compact at-a-glance table of the most-looked-up fields
(ID, skin tone, thigh type, bust + hips node scaling, jiggle tier), grouped by
unit. Picking one character prints the full detail block (also height / head /
ribbon), so a modder can read stock values before editing a bundle.
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

    # single character -> full detail block
    if len(ids) == 1:
        for line in charinfo.describe(ids[0]):
            job.log(line)
        job.progress(1, 1)
        return "shown 1 character"

    # all characters -> compact summary table, grouped by unit
    job.log("Character body reference. Bust/Hips = canonical node scaling (x/y/z);")
    job.log("Thigh = UpLeg type; Jig = breast-physics (dyna) tier. Hips is the reference")
    job.log("costume's value ('-' = not scaled). Pick one character above for full detail.")
    last_unit = None
    for i, cid in enumerate(ids):
        u = charinfo.unit_of(cid)
        if u != last_unit:
            job.log("")
            job.log(f"-- {u} " + "-" * max(0, 44 - len(u)))
            job.log(charinfo.summary_header())
            last_unit = u
        job.log(charinfo.summary_row(cid))
        job.progress(i + 1, len(ids))
    return f"shown {len(ids)} characters"
