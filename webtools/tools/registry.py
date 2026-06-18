"""Tool metadata + form field schemas, consumed by the frontend to render UIs and
by the server to dispatch runs. Field `mode` (single|batch|None) lets the UI show
the right inputs for the chosen run mode.

Field types: path (file picker), dir (folder picker), text, number, checkbox, select.
"""
from webtools.tools.breast import (
    DEFAULT_BREAST_NAME, DEFAULT_DYNA_PATTERNS, run_dyna, run_size,
)
from webtools.tools.skirt import DEFAULT_SKIRT_PATTERNS, run_skirt
from webtools.tools.texture import TEXTURE_FORMATS, run_texture


# ---- reusable field fragments ------------------------------------------------
def _in_single():
    return {"name": "in_path", "label": "Input bundle", "type": "path",
            "mode": "single", "root": "extracted", "help": "A single UnityFS asset bundle."}


def _in_batch():
    return {"name": "in_dir", "label": "Input folder", "type": "dir",
            "mode": "batch", "root": "extracted", "help": "All bundles under here are processed."}


def _out_dir():
    return {"name": "out_dir", "label": "Output folder", "type": "dir",
            "root": "modded", "help": "Where modified bundles are written."}


def _prefix_suffix():
    return [
        {"name": "prefix", "label": "Filename prefix", "type": "text", "default": ""},
        {"name": "suffix", "label": "Filename suffix", "type": "text", "default": "_mod"},
    ]


def _common_io():
    return [_in_single(), _in_batch(), _out_dir(), *_prefix_suffix()]


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
            {"name": "set_x", "label": "set scale X", "type": "number", "default": "",
             "help": "Absolute scale; blank to skip this axis."},
            {"name": "set_y", "label": "set scale Y", "type": "number", "default": ""},
            {"name": "set_z", "label": "set scale Z", "type": "number", "default": ""},
            {"name": "add_x", "label": "add ΔX", "type": "number", "default": "0"},
            {"name": "add_y", "label": "add ΔY", "type": "number", "default": "0"},
            {"name": "add_z", "label": "add ΔZ", "type": "number", "default": "0"},
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
            {"name": "set_x", "label": "set scale X", "type": "number", "default": "",
             "help": "Absolute scale; blank to skip. Uniform 0.85 = shorter, 1.15 = longer."},
            {"name": "set_y", "label": "set scale Y", "type": "number", "default": ""},
            {"name": "set_z", "label": "set scale Z", "type": "number", "default": ""},
            {"name": "add_x", "label": "add ΔX", "type": "number", "default": "0"},
            {"name": "add_y", "label": "add ΔY", "type": "number", "default": "0"},
            {"name": "add_z", "label": "add ΔZ", "type": "number", "default": "0"},
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
            {"name": "img_folder", "label": "Image folder", "type": "dir", "root": "home",
             "help": "Replacement images named after the texture (e.g. ch0107_co0001_body.png)."},
            {"name": "format", "label": "Texture format", "type": "select",
             "options": TEXTURE_FORMATS, "default": "Keep Original"},
            {"name": "recursive", "label": "Recurse subfolders", "type": "checkbox",
             "default": True, "mode": "batch"},
        ],
    },
]

_BY_ID = {t["id"]: t for t in TOOLS}


def get_tool(tool_id):
    return _BY_ID.get(tool_id)


def public_tools():
    """The registry without the (non-serialisable) run callables."""
    out = []
    for t in TOOLS:
        out.append({k: v for k, v in t.items() if k != "run"})
    return out
