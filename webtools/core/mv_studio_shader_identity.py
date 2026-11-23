"""Identify an original SIFAS shader by its ShaderLab name (Shader.m_ParsedForm.m_Name).

A material names its shader by (serialized file, path ID). That pair is only an
identity for one copy of the shader: a timeline bundle can embed its own copy
(12007 carries AS/General/Transparent at path ID 7151384334892346267 in its own
CAB), and the client compiles both copies from the same ShaderLab source. So
the name decides, and the (CAB, path ID) table below is only used when the
shader object itself is not loaded (the stage preview reads no shader bundles):
each row was verified against the shared shader bundle that holds it.
"""

import weakref

from . import model_viewer as viewer


# Verified shared shader bundle identities: (serialized file, path ID) -> m_ParsedForm.m_Name.
KNOWN = {
    ("cab-618a998abe328b9a2b05b370a5907b3e", 8330475765356442367): "AS/General/Opaque",
    ("cab-adf9ba7b61bd035c754bf74ae44927cb", 7151384334892346267): "AS/General/Transparent",
    ("cab-6cf8387efa4151b6220fceb9384d0e8e", 7983779172275908372): "AS/Rimlight/Opaque",
    ("cab-31fad648db7286e0012ae8cc07024bff", -1043432931367049882): "AS/Color/Opaque",
    ("cab-da18667fd7e5e991d56b5d877869e6c6", 7366096703533297961): "AS/Coloring/Transparent",
    ("cab-a44cd34f6481b592fc0475c6e5d23bfa", 9060382612279247893): "AS/FlashLight",
    ("cab-fc0511ca63f2d94bbfe211260d08ddd1", -6509019661097744245): "AS/Stage",
    ("cab-4004e36071ab5261ebac9281e0eccd75", 3926475870365283136): "AS/Penlight",
}

# A loaded Shader's type tree holds its compiled programs; read its name once per object.
_NAMES = weakref.WeakKeyDictionary()


def _loaded_name(shader):
    try:
        cache = _NAMES.setdefault(shader.assets_file, {})
    except TypeError:
        cache = {}
    if shader.path_id not in cache:
        form = shader.read_typetree().get("m_ParsedForm") or {}
        name = form.get("m_Name") if isinstance(form, dict) else None
        cache[shader.path_id] = name if isinstance(name, str) else None
    return cache[shader.path_id]


def name(material, tree):
    """The ShaderLab name of a material's shader, or None when it cannot be identified."""
    pointer = (tree or {}).get("m_Shader") or {}
    if not isinstance(pointer, dict) or not pointer.get("m_PathID"):
        return None
    shader = viewer._ref(material, pointer)
    if shader is not None:
        return _loaded_name(shader) if shader.type.name == "Shader" else None
    file_id = pointer.get("m_FileID", 0)
    references = material.assets_file.externals
    if type(file_id) is not int or not 0 < file_id <= len(references):
        return None
    cab = references[file_id - 1].path.replace("\\", "/").rsplit("/", 1)[-1].lower()
    return KNOWN.get((cab, pointer.get("m_PathID")))


def matches(material, tree, expected):
    return name(material, tree) == expected
