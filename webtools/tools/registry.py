"""Tool metadata + form field schemas, consumed by the frontend to render UIs and
by the server to dispatch runs. Field `mode` (single|batch|None) lets the UI show
the right inputs for the chosen run mode; `required` fields are validated client-
and server-side.

Field types: path (file picker), dir (folder picker), text, number, checkbox, select.
"""
from webtools.tools.breast import (
    DEFAULT_BREAST_NAME, DEFAULT_DYNA_PATTERNS, run_dyna, run_size,
)
from webtools.tools.skirt import DEFAULT_SKIRT_PATTERNS, run_skirt
from webtools.tools.texture import TEXTURE_FORMATS, run_texture
from webtools.tools.bodymod import (
    DEFAULT_HIPS_NAME, DEFAULT_UPLEG_PATTERNS, NODE_SCALING_MODES,
    run_hips, run_node_scaling, run_upleg,
)
from webtools.tools.costume import (
    run_costume_packer, run_costume_transplant, run_iosapk_import,
)
from webtools.tools.mesh import run_fix_export, run_mesh_baker
from webtools.tools.renamer import run_renamer

from webtools import i18n


# ---- reusable field fragments ------------------------------------------------
def _in_single():
    return {"name": "in_path", "label": "Input bundle", "type": "path", "required": True,
            "mode": "single", "root": "extracted", "help": "A single UnityFS asset bundle."}


def _in_batch():
    return {"name": "in_dir", "label": "Input folder", "type": "dir", "required": True,
            "mode": "batch", "root": "extracted", "help": "All bundles under here are processed."}


def _out_dir():
    return {"name": "out_dir", "label": "Output folder", "type": "dir", "required": True,
            "root": "modded", "help": "Where modified bundles are written."}


def _prefix_suffix(suffix_default="_mod"):
    return [
        {"name": "prefix", "label": "Filename prefix", "type": "text", "default": ""},
        {"name": "suffix", "label": "Filename suffix", "type": "text", "default": suffix_default},
    ]


def _common_io(suffix_default="_mod"):
    return [_in_single(), _in_batch(), _out_dir(), *_prefix_suffix(suffix_default)]


def _xyz(prefix_label, names, default="", help_first=None):
    fields = []
    for axis, name in zip(("X", "Y", "Z"), names):
        f = {"name": name, "label": f"{prefix_label} {axis}", "type": "number", "default": default}
        if help_first and axis == "X":
            f["help"] = help_first
        fields.append(f)
    return fields


# ---- the tools ---------------------------------------------------------------
TOOLS = [
    {
        "id": "breast_dyna",
        "label": "Breast Physics (Dyna)",
        "description": "Edit SwingBone physics (stiffness / drag / rotation limits) on breast bones.",
        "modes": ["single", "batch"],
        "run": run_dyna,
        "fields": [
            *_common_io(),
            {"name": "patterns", "label": "Bone name patterns", "type": "text",
             "default": ", ".join(DEFAULT_DYNA_PATTERNS),
             "help": "Comma/space separated SwingBone GameObject name patterns."},
            {"name": "_phys_preset", "label": "Physics feel (preset)", "type": "preset",
             "options": [
                 {"label": "(custom)", "set": {}},
                 {"label": "Softer (0.01 / 0.2)", "set": {"stiff": "0.01", "drag": "0.2"}},
                 {"label": "Soft (0.02 / 0.3)", "set": {"stiff": "0.02", "drag": "0.3"}},
                 {"label": "Firm (0.05 / 0.5)", "set": {"stiff": "0.05", "drag": "0.5"}},
             ],
             "help": "Fills stiffnessForce / dragForce below; you can still fine-tune."},
            {"name": "stiff", "label": "stiffnessForce", "type": "number", "default": "",
             "help": "Blank = leave unchanged."},
            {"name": "drag", "label": "dragForce", "type": "number", "default": "",
             "help": "Blank = leave unchanged."},
            {"name": "low_dy", "label": "low RotationLimit Δy", "type": "number", "default": "0"},
            {"name": "low_dz", "label": "low RotationLimit Δz", "type": "number", "default": "0"},
            {"name": "high_dy", "label": "high RotationLimit Δy", "type": "number", "default": "0"},
            {"name": "high_dz", "label": "high RotationLimit Δz", "type": "number", "default": "0"},
            {"name": "use_character_specific", "label": "Auto per-character jiggle", "type": "checkbox",
             "default": False, "help": "Detect the character and tag the output with its jiggleN tier."},
        ],
    },
    {
        "id": "breast_size",
        "label": "Breast Size (LiveCore)",
        "description": "Edit LiveCoreMemberNodeScaling.scaleValues on the BreastSize node.",
        "modes": ["single", "batch"],
        "run": run_size,
        "fields": [
            *_common_io(),
            {"name": "breast_name", "label": "Scale node name", "type": "text",
             "default": DEFAULT_BREAST_NAME},
            {"name": "_size_preset", "label": "Size preset (by character)", "type": "preset",
             # canonical in-game sizes; see BREAST_*_PRESETS in sifas_breast_tuner.py
             "options": [
                 {"label": "(custom)", "set": {}},
                 {"label": "Rina  (0.61, 0.91, 0.85)", "set": {"set_x": "0.61", "set_y": "0.91", "set_z": "0.85"}},
                 {"label": "Nico  (0.64, 0.94, 0.88)", "set": {"set_x": "0.64", "set_y": "0.94", "set_z": "0.88"}},
                 {"label": "Rin  (0.72, 0.95, 0.90)", "set": {"set_x": "0.72", "set_y": "0.95", "set_z": "0.90"}},
                 {"label": "Umi / Ruby / Kasumi  (0.80, 0.96, 0.92)", "set": {"set_x": "0.80", "set_y": "0.96", "set_z": "0.92"}},
                 {"label": "Honoka / Maki  (0.90, 0.98, 0.96)", "set": {"set_x": "0.90", "set_y": "0.98", "set_z": "0.96"}},
                 {"label": "Yoshiko / Shioriko  (0.95, 0.99, 0.98)", "set": {"set_x": "0.95", "set_y": "0.99", "set_z": "0.98"}},
                 {"label": "Chika / You / Ayumu  (1.04, 1.02, 1.04)", "set": {"set_x": "1.04", "set_y": "1.02", "set_z": "1.04"}},
                 {"label": "Hanayo / Setsuna  (1.08, 1.04, 1.08)", "set": {"set_x": "1.08", "set_y": "1.04", "set_z": "1.08"}},
                 {"label": "Hanamaru / Ai  (1.12, 1.06, 1.12)", "set": {"set_x": "1.12", "set_y": "1.06", "set_z": "1.12"}},
                 {"label": "Lanzhu  (1.14, 1.07, 1.14)", "set": {"set_x": "1.14", "set_y": "1.07", "set_z": "1.14"}},
                 {"label": "Eli / Kanan / Kanata  (1.16, 1.08, 1.16)", "set": {"set_x": "1.16", "set_y": "1.08", "set_z": "1.16"}},
                 {"label": "Mari  (1.20, 1.10, 1.20)", "set": {"set_x": "1.20", "set_y": "1.10", "set_z": "1.20"}},
                 {"label": "Karin  (1.22, 1.11, 1.22)", "set": {"set_x": "1.22", "set_y": "1.11", "set_z": "1.22"}},
                 {"label": "Nozomi  (1.30, 1.15, 1.30)", "set": {"set_x": "1.30", "set_y": "1.15", "set_z": "1.30"}},
                 {"label": "Emma  (1.30, 1.18, 1.30)", "set": {"set_x": "1.30", "set_y": "1.18", "set_z": "1.30"}},
             ],
             "help": "Fills the X/Y/Z scale below with a character's in-game breast size."},
            *_xyz("set scale", ("set_x", "set_y", "set_z"),
                  help_first="Absolute scale; blank to skip this axis."),
            *_xyz("add Δ", ("add_x", "add_y", "add_z"), default="0"),
        ],
    },
    {
        "id": "skirt",
        "label": "Skirt Length",
        "description": "Scale skirt bone Transforms to lengthen or shorten skirts.",
        "modes": ["single", "batch"],
        "run": run_skirt,
        "fields": [
            *_common_io(),
            {"name": "patterns", "label": "Skirt GO name patterns", "type": "text",
             "default": ", ".join(DEFAULT_SKIRT_PATTERNS)},
            {"name": "_len_preset", "label": "Length preset", "type": "preset",
             "options": [
                 {"label": "(custom)", "set": {}},
                 {"label": "Shorter (0.85)", "set": {"set_x": "0.85", "set_y": "0.85", "set_z": "0.85"}},
                 {"label": "Longer (1.15)", "set": {"set_x": "1.15", "set_y": "1.15", "set_z": "1.15"}},
                 {"label": "Reset (1.0)", "set": {"set_x": "1.0", "set_y": "1.0", "set_z": "1.0"}},
             ],
             "help": "Skirts usually scale uniformly; this fills X/Y/Z together."},
            *_xyz("set scale", ("set_x", "set_y", "set_z"),
                  help_first="Absolute scale; blank to skip. Uniform 0.85 = shorter, 1.15 = longer."),
            *_xyz("add Δ", ("add_x", "add_y", "add_z"), default="0"),
        ],
    },
    {
        "id": "texture",
        "label": "Texture Importer",
        "description": "Replace Texture2D images inside bundles from a folder of PNG/JPG files.",
        "modes": ["single", "batch"],
        "run": run_texture,
        "fields": [
            _in_single(), _in_batch(), _out_dir(), *_prefix_suffix(),
            {"name": "img_folder", "label": "Image folder", "type": "dir", "required": True, "root": "home",
             "help": "Replacement images named after the texture (e.g. ch0107_co0001_body.png)."},
            {"name": "format", "label": "Texture format", "type": "select",
             "options": TEXTURE_FORMATS, "default": "Keep Original"},
            {"name": "recursive", "label": "Recurse subfolders", "type": "checkbox",
             "default": True, "mode": "batch"},
        ],
    },
    {
        "id": "hips_size",
        "label": "Hips Size",
        "description": "Edit LiveCore scaling on the HipsSize node.",
        "modes": ["single", "batch"],
        "run": run_hips,
        "fields": [
            *_common_io(),
            {"name": "target_go_name", "label": "Scale node name", "type": "text",
             "default": DEFAULT_HIPS_NAME},
            *_xyz("set scale", ("set_x", "set_y", "set_z"),
                  help_first="Absolute scale; blank to skip this axis."),
            *_xyz("add Δ", ("add_x", "add_y", "add_z"), default="0"),
        ],
    },
    {
        "id": "node_scaling",
        "label": "Node Scaling Fix",
        "description": "Repair LiveCoreMemberNodeScaling entries that don't match the bone's local transform.",
        "modes": ["single", "batch"],
        "run": run_node_scaling,
        "fields": [
            *_common_io("_nodefix"),
            {"name": "mode_select", "label": "Repair mode", "type": "select",
             "options": NODE_SCALING_MODES, "default": "rebase",
             "help": "rebase = re-anchor to current local; neutralize = reset; none = scan only."},
        ],
    },
    {
        "id": "upleg_collider",
        "label": "UpLeg Swing Collider",
        "description": "Edit SwingCollider radius/offset on upper-leg bones.",
        "modes": ["single", "batch"],
        "run": run_upleg,
        "fields": [
            *_common_io(),
            {"name": "patterns", "label": "Bone name patterns", "type": "text",
             "default": ", ".join(DEFAULT_UPLEG_PATTERNS)},
            {"name": "set_radius", "label": "set radius", "type": "number", "default": "",
             "help": "Blank = leave unchanged."},
            {"name": "add_radius", "label": "add radius Δ", "type": "number", "default": "0"},
            *_xyz("set offset", ("set_off_x", "set_off_y", "set_off_z")),
            *_xyz("add offset Δ", ("add_off_x", "add_off_y", "add_off_z"), default="0"),
        ],
    },
    {
        "id": "costume_packer",
        "label": "Costume Mod Packer",
        "description": "Package costume bundles into installer .zip packs (with thumbnail).",
        "modes": ["single", "batch"],
        "run": run_costume_packer,
        "fields": [
            _in_single(), _in_batch(),
            {"name": "out_dir", "label": "Output folder (zips)", "type": "dir", "required": True,
             "root": "modded"},
            {"name": "auto_chara_id", "label": "Auto-detect character ID", "type": "checkbox", "default": True},
            {"name": "manual_chara_id", "label": "Manual character ID", "type": "number", "default": "0",
             "help": "Used when auto-detect is off or fails."},
            {"name": "thumbnail_size", "label": "Thumbnail size", "type": "number", "default": "256"},
            {"name": "combine_pairs", "label": "Combine Android+iOS pairs", "type": "checkbox",
             "default": True, "mode": "batch"},
        ],
    },
    {
        "id": "costume_transplant",
        "label": "Costume Transplant",
        "description": "Graft a donor costume's body mesh onto a target wearer model.",
        "modes": ["single"],
        "run": run_costume_transplant,
        "fields": [
            {"name": "donor", "label": "Donor (costume) bundle", "type": "path", "required": True,
             "root": "extracted"},
            {"name": "target", "label": "Target (wearer) bundle", "type": "path", "required": True,
             "root": "extracted"},
            {"name": "out_dir", "label": "Output folder", "type": "dir", "required": True, "root": "modded"},
            {"name": "suffix", "label": "Filename suffix", "type": "text", "default": "_transplant"},
            {"name": "preserve_physics", "label": "Preserve costume physics", "type": "checkbox", "default": False},
            {"name": "realign", "label": "Realign bones", "type": "checkbox", "default": True},
            {"name": "restore_collision", "label": "Restore collision", "type": "checkbox", "default": True},
            {"name": "worldspace", "label": "World-space normalize", "type": "checkbox", "default": True},
            {"name": "fix_nodescaling", "label": "Fix node scaling", "type": "checkbox", "default": True},
        ],
    },
    {
        "id": "mesh_baker",
        "label": "Mesh Baker",
        "description": "Bake bone scale/rotate/translate into mesh vertices.",
        "modes": ["single", "batch"],
        "run": run_mesh_baker,
        "fields": [
            *_common_io("_baked"),
            {"name": "thigh", "label": "Thigh preset", "type": "select", "default": "",
             "options": [
                 {"value": "", "label": "(none)"},
                 {"value": "slim:default", "label": "slim → default"},
                 {"value": "slim:thick", "label": "slim → thick"},
                 {"value": "default:slim", "label": "default → slim"},
                 {"value": "default:thick", "label": "default → thick"},
                 {"value": "thick:slim", "label": "thick → slim"},
                 {"value": "thick:default", "label": "thick → default"},
             ],
             "help": "One-click thigh resize: scales both UpLeg bones with child compensation."},
            {"name": "target_spec", "label": "Target spec(s) — advanced", "type": "text", "default": "",
             "help": "Optional manual bones, one per line: Bone;s=1.1,1.1,1.1;r=0,0,0;t=0,0,0;comp=1"},
            {"name": "recompute_normals", "label": "Recompute normals", "type": "checkbox", "default": True},
            {"name": "hierarchical", "label": "Hierarchical skinning", "type": "checkbox", "default": True},
        ],
    },
    {
        "id": "iosapk_import",
        "label": "iOS/APK Selective Import",
        "description": "Copy matching objects from a donor into a target by pathID (iOS/APK variant transfer).",
        "modes": ["single", "batch"],
        "run": run_iosapk_import,
        "fields": [
            {"name": "donor", "label": "Donor bundle", "type": "path", "required": True,
             "mode": "single", "root": "extracted"},
            {"name": "target", "label": "Target bundle", "type": "path", "required": True,
             "mode": "single", "root": "extracted"},
            {"name": "donor_dir", "label": "Donor folder", "type": "dir", "required": True,
             "mode": "batch", "root": "extracted"},
            {"name": "target_dir", "label": "Target folder", "type": "dir", "required": True,
             "mode": "batch", "root": "extracted"},
            {"name": "out_dir", "label": "Output folder", "type": "dir", "required": True, "root": "modded"},
            {"name": "prefix", "label": "Filename prefix", "type": "text", "default": "", "mode": "batch"},
            {"name": "suffix", "label": "Filename suffix", "type": "text", "default": "_import"},
            {"name": "import_new_objects", "label": "Import new objects (transplant grafts)",
             "type": "checkbox", "default": True},
            {"name": "name_include", "label": "Name include (optional)", "type": "text", "default": ""},
            {"name": "name_exclude", "label": "Name exclude (optional)", "type": "text", "default": ""},
        ],
    },
    {
        "id": "renamer",
        "label": "Bundle Renamer (by texture)",
        "description": "Copy bundles into a folder, renamed by their ch####_co#### texture name (originals untouched).",
        "modes": ["batch"],
        "run": run_renamer,
        "fields": [
            {"name": "in_dir", "label": "Input folder", "type": "dir", "required": True, "root": "modded",
             "help": "Folder of bundles to rename."},
            {"name": "out_dir", "label": "Output folder", "type": "dir", "required": True, "root": "modded",
             "help": "Renamed copies go here."},
            {"name": "include_costume_id", "label": "Include costume ID", "type": "checkbox", "default": False},
            {"name": "remove_special_chars", "label": "Remove special characters", "type": "checkbox", "default": False},
            {"name": "filename_length_limit", "label": "Filename length limit", "type": "number", "default": "",
             "help": "Blank = no limit."},
        ],
    },
    {
        "id": "fix_export",
        "label": "Fix Bundle Export (world-space)",
        "description": "Normalize skinned meshes to world space for correct FBX export (in-game rendering unchanged).",
        "modes": ["single", "batch"],
        "run": run_fix_export,
        "fields": [
            *_common_io("_fixed"),
        ],
    },
]

_BY_ID = {t["id"]: t for t in TOOLS}


def get_tool(tool_id):
    return _BY_ID.get(tool_id)


def public_tools(lang=None):
    """The registry without the (non-serialisable) run callables.

    Display text (tool ``label``/``description`` and each field's
    ``label``/``help``) is translated into *lang*; English is the fallback.
    Field ``options`` are left untranslated because their values double as the
    identifiers the server dispatches on.
    """
    out = []
    for t in TOOLS:
        tool = {}
        for k, v in t.items():
            if k == "run":
                continue
            if k in ("label", "description"):
                tool[k] = i18n.tr(v, lang=lang)
            elif k == "fields":
                tool[k] = [_translate_field(f, lang) for f in v]
            else:
                tool[k] = v
        out.append(tool)
    return out


def _translate_field(field, lang):
    f = dict(field)
    if "label" in f:
        f["label"] = i18n.tr(f["label"], lang=lang)
    if "help" in f:
        f["help"] = i18n.tr(f["help"], lang=lang)
    # Preset option labels are display-only (the value is the `set` dict), so
    # they are safe to translate; normal select options are left untranslated
    # because their values double as dispatch identifiers.
    if f.get("type") == "preset" and isinstance(f.get("options"), list):
        f["options"] = [
            {**o, "label": i18n.tr(o["label"], lang=lang)}
            if isinstance(o, dict) and "label" in o else o
            for o in f["options"]
        ]
    return f
