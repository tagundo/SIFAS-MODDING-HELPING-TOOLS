"""Compare a game runtime value dump with MV Studio's evaluation of it, per asset type.

    python tests/mv_runtime_compare.py --game GAME(.json|.json.gz|job.log) --editor EDITOR.json.gz --out REPORT_DIR
        [--keys 12035-runtime-keys.json] [--tolerances tol.json] [--phase auto|-1|0|1]
        [--baseline OLD/report.json] [--fail-on-regression] [--require-valid]

Both documents use schema sifas-mv-runtime-dump/1. The game writes Unity values
("unity-lh"), the editor writes three.js values with X mirrored
("three-rh-mirror-x"); class Conventions below is the ONLY place where a
position, rotation, matrix, texture transform, key or name is converted. A game
document whose side is "editor" is joined record by record without any
conversion (an editor-vs-editor check that must be identically zero).

Records join on clock.directorTime: every editor record names its game record
(sourceRecord) and an evaluation phase of -1, 0 or +1 game frames. The phase is
calibrated from the camera pose, then every asset type is compared at that
phase. Each comparison has a tolerance; score = error / tolerance, and a score
above 1 is a discrepancy (boundaries are inclusive). Exact quantities
(visibility, quality values, texture dimensions) score EXACT_SCORE on a
mismatch. Camera and aspect values of frame records within one frame of a
camera cut are reported but not ranked.

Samples are grouped by (type, key, metric): one group is one defect, carrying
its worst sample, its sample count and the first and last director time. The
ranking, the beyond-tolerance counts and the regression check all work on
groups, so a longer run of the same defect neither floods the top 25 nor
counts as a regression.

The editor must run at the quality the game ran (header.quality.values). When
the game recorded none, or a value still differs, the report is marked
validity "invalid:quality": quality-gated asset types (post, visibility of
quality-gated nodes, springs, render resolution) are then not comparable.

Outputs REPORT_DIR/report.json (schema sifas-mv-runtime-compare/2), report.md
and worst.csv. The exit code is 0, 2 when --fail-on-regression is given and
the result regresses against --baseline, or 3 when --require-valid is given and
the report is invalid.
"""
import argparse
import base64
import csv
from collections import Counter, defaultdict
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
import zlib

SCHEMA = "sifas-mv-runtime-dump/1"
REPORT_SCHEMA = "sifas-mv-runtime-compare/2"
EXACT_SCORE = 1000.0
TYPES = ("camera", "aspect", "globals", "renderSettings", "lights", "visibility", "transforms", "materials", "post",
         "particles", "quality", "springs", "coverage")
DIAGNOSTIC_TYPES = {"springs", "particles"}
TIME_GLOBALS = {"_MusicTime", "_SelfTime", "_Time"}
TIMESTAMP = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z ")
PROBE_BLOB = "rtdump-probe"
WORSENED_FACTOR = 2.0       # a group beyond tolerance in both reports regresses when its worst score at least doubles

DEFAULT_TOLERANCES = {
    "fovDeg": 1e-3, "aspectRel": 1e-5, "projectionRel": 1e-4, "projectionZeroAbs": 1e-6, "nearAbs": 1e-5, "farRel": 1e-5,
    "cameraPositionM": 1e-3, "cameraRotationDeg": 0.05, "correction": 1e-6, "worldToCamera": 1e-4, "ndc": 2e-3,
    "globalAbs": 1e-4, "color": 1 / 512, "floatRel": 1e-4, "floatAbs": 1e-5, "stAbs": 1e-5,
    "stagePositionM": 1e-3, "stageRotationDeg": 0.1, "scaleRel": 1e-3, "bonePositionM": 5e-3, "boneRotationDeg": 0.5,
    "springRotationDeg": 5.0, "blendShapeWeight": 1.0, "authoredMatchDeg": 1e-3, "authoredFraction": 0.95,
    "beatAbs": None,          # None: globalAbs. Device dumps: 0.25 (the CRI beat callback lagged <= 0.18 beat on Redroid run 2)
    "particleCountRel": 0.1, "particleCountAbs": 2,
}
# Unity Time.maximumDeltaTime default (1/3 s): a frame whose deltaTime is clamped to it advanced the director by
# more than deltaTime (the director follows the music clock), so t - deltaTime is not the previous frame's time.
MAX_DELTA_TIME = 1 / 3
# Cameras besides the main camera that draw stage content into the MV picture (LiveCoreCameraManager.overlayCamera:
# layer 20 overlay effects at qualities with StageOverlayEffect, cullingMask 0 otherwise).
PICTURE_CAMERAS = {"camera:overlay"}
# Material properties the LLAS lighting components write with Material.SetColor/SetFloat (LivePropAmbient,
# LivePropRimlight, LiveCoreStageAmbient, LiveCoreMemberRimlight, LivePenlightMixer): the game dump reads them from
# the material, so an editor shader uniform u<Name> is compared with _<Name>. AnimationTrack/Animator curves go
# through MaterialPropertyBlocks, which the game dump does not read (header.limits.propertyBlocks false): the editor
# lists the uniforms its curves drive (materials[].curveDriven) and those are reported as not comparable.
SHADER_MATERIAL_PROPERTIES = {"_TintColor", "_AmbientColor", "_BlendColor", "_RimlightColor", "_RimlightDirection",
                              "_RimglightIntensity", "_RimglightPower", "_BeatLength", "_RandomBrightness",
                              "_RandomSwingIntensity", "_RandomDelay", "_RandomUp"}
# AS/Member cheek: MemberCheekBase writes _CheekIntensity/_CheekTexArrayIndex with Material.SetFloat (ApplyCheek
# 0x27c4ccc) and toggles only the _CHEEK_ON keyword (ApplyEnable 0x27c4c14); MemberCheekMixer.PostProcess (0x26e9344)
# turns the keyword off and keeps the floats of the last frame a clip was processed in. The [Toggle] float _CHEEK is
# never written by the client and is no uniform of the compiled shader, so it does not tell whether the cheek is drawn:
# the floats are compared as the material holds them, and the drawn variant through the game's keywords (renderer
# material slots, compare_member_variant).
CHEEK_TOGGLE = "_CHEEK"
# Editor shader uniforms named after their role rather than the Unity property (AS/FlashLight _Speed/_Length,
# AS/General/Transparent and AS/FlashLight _TintColor). uTextureST is _MainTex's scale/offset (textureSTSpace).
SHADER_UNIFORM_ALIASES = {"uTint": "_TintColor", "uSpeed": "_Speed", "uLength": "_Length"}
BEAT_GLOBALS = {"_Beat"}
VECTOR_GLOBALS = {"_RenderTextureResolution"}   # compared on .v (x, y), exact
# worldToCamera is column-major: elements 12-14 are its translation in metres, compared with the
# camera position tolerance; the other elements are unitless rotation and projective terms.
W2C_TRANSLATION = (12, 13, 14)
# LiveCoreStageEffect.Initialize (0x2f6f4c4) gives every AxisBillboard below the stage effect its camera targets
# (0x2f6fa68: the main camera's and the stage display camera's transforms). AxisBillboard.OnWillRenderObject
# (0x27bf944) turns the Transform about its own up axis (RunAxisBillboardY 0x27bfc14) only when Camera.current is a
# target or, with split screen on, one of LiveSplitScreenEffect.SubCameraTransforms: a cone no target camera draws
# keeps the turn of its last draw while its Animator parents move on. Its up axis (the beam) is the parents' and
# is compared on every sample; the turn about it is draw history. A game renderers record says whether the camera
# drew it (isVisible); a stage node record does not, so a billboard stage node keeps the whole comparison only where
# the editor reports that the live camera draws it (axisBillboardDrawn, with the live camera's turn), and is compared
# on its up axis elsewhere.
AXIS_BILLBOARD_CLASS = "LLAS.Components.AxisBillboard.AxisBillboard"
STAGE_EFFECT_CLASS = "LLAS.Scene.Live.Components.LiveCoreStageEffect"


class DumpError(ValueError):
    pass


# ------------------------------------------------------------------ math

def qmul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return [aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz]


def qnorm(q):
    length = math.sqrt(sum(value * value for value in q)) or 1.0
    return [value / length for value in q]


def qangle(a, b):
    """Rotation between two unit quaternions in degrees: 2*acos|dot| in the stable form
    4*atan2(|a - b|, |a + b|) on the closer hemisphere, which is exactly 0 for equal inputs."""
    a, b = qnorm(a), qnorm(b)
    if sum(x * y for x, y in zip(a, b)) < 0:
        b = [-value for value in b]
    minus = math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))
    plus = math.sqrt(sum((x + y) ** 2 for x, y in zip(a, b)))
    return math.degrees(4 * math.atan2(minus, plus))


def qlog_deg(a, b):
    """Rotation vector (degrees) of a * conj(b), hemisphere chosen so w >= 0."""
    a, b = qnorm(a), qnorm(b)
    x, y, z, w = qmul(a, [-b[0], -b[1], -b[2], b[3]])
    if w < 0:
        x, y, z, w = -x, -y, -z, -w
    length = math.sqrt(x * x + y * y + z * z)
    if length < 1e-15:
        return [0.0, 0.0, 0.0]
    angle = math.degrees(2 * math.atan2(length, w))
    return [x / length * angle, y / length * angle, z / length * angle]


def qrotate(q, v):
    """Vector v rotated by the unit quaternion q (x, y, z, w)."""
    x, y, z, w = qnorm(q)
    tx, ty, tz = 2 * (y * v[2] - z * v[1]), 2 * (z * v[0] - x * v[2]), 2 * (x * v[1] - y * v[0])
    return [v[0] + w * tx + y * tz - z * ty, v[1] + w * ty + z * tx - x * tz, v[2] + w * tz + x * ty - y * tx]


def axis_angle(a, b, axis=(0.0, 1.0, 0.0)):
    """Angle in degrees between the local `axis` of two rotations: their swing, without the twist about that axis."""
    u, v = qrotate(a, axis), qrotate(b, axis)
    cross = math.sqrt((u[1] * v[2] - u[2] * v[1]) ** 2 + (u[2] * v[0] - u[0] * v[2]) ** 2 + (u[0] * v[1] - u[1] * v[0]) ** 2)
    return math.degrees(math.atan2(cross, sum(x * y for x, y in zip(u, v))))


def distance(a, b):
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def mat_mul(a, b):
    """Column-major 4x4 product a*b."""
    return [sum(a[k * 4 + r] * b[c * 4 + k] for k in range(4)) for c in range(4) for r in range(4)]


def mat_vec(m, v):
    return [sum(m[c * 4 + r] * v[c] for c in range(4)) for r in range(4)]


def project(projection, view, point):
    clip = mat_vec(projection, mat_vec(view, [point[0], point[1], point[2], 1.0]))
    if clip[3] <= 1e-9:
        return None
    return [clip[0] / clip[3], clip[1] / clip[3], clip[2] / clip[3]]


def stats(values):
    values = sorted(value for value in values if value is not None and math.isfinite(value))
    if not values:
        return None
    at = lambda q: values[min(len(values) - 1, int(q * (len(values) - 1) + 0.5))]  # noqa: E731
    return {"n": len(values), "p50": at(0.5), "p95": at(0.95), "max": values[-1], "mean": statistics.fmean(values)}


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def vector(value, length=None):
    return isinstance(value, list) and all(number(item) for item in value) and (length is None or len(value) == length)


# ------------------------------------------------------------------ conventions

class Conventions:
    """Every editor -> Unity conversion of schema section 1.4, and nothing else.

    All conversions are involutions or have explicit inverses, which tests import."""

    S = (-1.0, 1.0, 1.0, 1.0)            # S4 = diag(-1, 1, 1, 1)
    H0_LEFT = (-1.0, 1.0, -1.0, 1.0)     # diag(-1, 1, -1, 1)
    HYPOTHESES = ("H180", "H0")
    QUALITY = {
        "PostEffect": "posteffect", "FrameRate60Fps": "frame_rate_60fps", "MemberSwingBone": "member_swing_bone_mv",
        "Quality": "quality_mode", "RenderingResolution": "rendering_resolution", "BaseLight": "base_light",
        "StageAmbient": "stage_ambient", "StageAnimation": "stage_animation", "StageColoring": "stage_coloring",
        "StageControl": "stage_control", "StageOverlayEffect": "stage_overlay_effect", "StageFlashLight": "stage_flash_light",
        "StageDisplay": "stage_display", "StageEmissive": "stage_emissive", "StageAudience": "stage_audience",
        "StageCubemap": "stage_cubemap", "MemberAmbient": "member_ambient", "MemberRimLight": "member_rim_light",
        "MemberSpotLightShaft": "member_spot_light_shaft", "MemberSpotLightArea": "member_spot_light_area",
        "PropAmbient": "prop_ambient", "PropRimLight": "prop_rim_light", "SplitScreen": "split_screen",
    }
    QUALITY_IGNORED = {"set_id"}         # the preset's catalog row, not a scene setting
    STAGE_UNIFORMS = {"tint": "_TintColor", "ambient": "_AmbientColor", "blendColor": "_BlendColor",
                      "mainUVTransform": "_MainTex", "mainMap": "_MainTex", "emissiveColor": "_EmissiveColor",
                      "emissiveIntensity": "_EmissiveIntensity", "mipBias": "_MainTexMipmapBias", "alphaCutoff": "_Cutoff"}
    EDITOR_ONLY = {"uResolutionRatio", "uOutlineScale", "uOutlineEdited", "uOutlineQuantized", "uBeat"}
    # Editor UV transforms exported with the glTF V flip (mv_studio_stage_materials: [sx, sy, ox, 1 - sy - oy]).
    V_FLIPPED_ST = {"mainUVTransform", "emissiveUVTransform"}
    SCOPE_ROOTS = (("effect", re.compile(r"^/EntryPoint/Live/Stages/[^/]+/Effect(?:/|$)")),
                   ("stage", re.compile(r"^/EntryPoint/Live/Stages/[^/]+(?:/|$)")))
    MEMBER_ROOT = re.compile(r"^/EntryPoint/Live/Members/Member(\d+)(?:/|$)")

    @staticmethod
    def position(p):
        """Editor position -> Unity position (its own inverse)."""
        return [-p[0], p[1], p[2]]

    @staticmethod
    def quaternion(q):
        """Editor quaternion -> Unity quaternion (mirror conjugation, its own inverse)."""
        return [q[0], -q[1], -q[2], q[3]]

    @classmethod
    def node_matrix(cls, m):
        """S4 * M * S4 for a column-major node matrix (its own inverse)."""
        return [m[c * 4 + r] * cls.S[r] * cls.S[c] for c in range(4) for r in range(4)]

    @classmethod
    def world_to_camera(cls, view, hypothesis="H180"):
        """Expected Unity worldToCameraMatrix from the editor's matrixWorldInverse."""
        left = cls.H0_LEFT if hypothesis == "H0" else (1.0, 1.0, 1.0, 1.0)
        return [view[c * 4 + r] * left[r] * cls.S[c] for c in range(4) for r in range(4)]

    @classmethod
    def editor_view(cls, world_to_camera, hypothesis="H180"):
        """Inverse of world_to_camera: the editor view that a game matrix implies."""
        return cls.world_to_camera(world_to_camera, hypothesis)

    @staticmethod
    def camera_component_rotation(rig_unity, hypothesis="H180"):
        """Unity Camera component rotation from its rig: H180 is a child turned 180 deg about Y."""
        return qmul(rig_unity, [0.0, 1.0, 0.0, 0.0]) if hypothesis == "H180" else list(rig_unity)

    @staticmethod
    def stage_node_key(binding, rel_path=None, crc=None):
        if crc is None:
            crc = zlib.crc32(str(rel_path or "").replace("\\", "/").encode("utf-8")) & 0xFFFFFFFF
        return f"stageNode:{binding}#{int(crc)}"

    @classmethod
    def quality_key(cls, name):
        if name in cls.QUALITY:
            return cls.QUALITY[name]
        return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)).lower()

    @classmethod
    def quality_name(cls, key):
        """Inverse of quality_key for the explicit table (used by tests and synthetic documents)."""
        for name, value in cls.QUALITY.items():
            if value == key:
                return name
        return "".join(part.capitalize() for part in key.split("_"))

    @classmethod
    def material_property(cls, name):
        """Unity property name for an editor property or uniform name; None when unmapped."""
        if name.startswith("_"):
            return name
        if name in cls.STAGE_UNIFORMS:
            return cls.STAGE_UNIFORMS[name]
        if name in cls.EDITOR_ONLY:
            return None
        if re.match(r"^u[A-Z]", name):
            return "_" + name[1:]
        return None

    @staticmethod
    def same_quality(game, editor):
        """A C# bool read as a raw field may arrive as 0/1; any other value compares exactly."""
        if isinstance(editor, bool) or isinstance(game, bool):
            flags = (0, 1)
            return game in flags and editor in flags and bool(game) == bool(editor)
        return game == editor

    @staticmethod
    def texture_st(st):
        """Editor glTF UV transform [sx, sy, ox, 1 - sy - oy] <-> Unity [sx, sy, ox, oy] (its own inverse)."""
        return [st[0], st[1], st[2], 1 - st[1] - st[3]]

    @staticmethod
    def object_name(name):
        """Unity object name without the Instantiate '(Clone)' and renderer.material ' (Instance)' suffixes."""
        return re.sub(r"(?:\(Clone\)| \(Instance\))+$", "", name or "")

    @staticmethod
    def blend_weight(weight, unit):
        return weight * 100.0 if unit == "influence01" else weight

    @staticmethod
    def renderer_scope_mesh(key):
        match = re.match(r"^renderer:(member\d+|stage|effect|other):(.*?)(?:#\d+)?$", key or "")
        return (match.group(1), match.group(2)) if match else None

    @classmethod
    def game_relative_path(cls, path, scope, member_roots=None):
        """Game GameObject path below its scope root: the Effect object (effect), the stage
        root (stage), the member's BodyPartManager object, else Member<N> (member<N>)."""
        if not isinstance(path, str):
            return None
        member = re.match(r"^member(\d+)$", scope or "")
        if member:
            root = (member_roots or {}).get(int(member.group(1)))
            if root and (path == root or path.startswith(root + "/")):
                return path[len(root) + 1:]
            match = cls.MEMBER_ROOT.match(path)
            return path[match.end():] if match else path.lstrip("/")
        for name, pattern in cls.SCOPE_ROOTS:
            if scope == name:
                match = pattern.match(path)
                return path[match.end():] if match else path.lstrip("/")
        return path.lstrip("/")

    @staticmethod
    def game_scope(path, scope):
        """A renderer outside /EntryPoint belongs to the additively loaded stage scene (m_live_stage.scene_name,
        e.g. bg0006_01_s1, whose roots such as /Model are scene roots): scope "stage", path below that root."""
        if scope == "other" and isinstance(path, str) and path.startswith("/") and not path.startswith("/EntryPoint/") \
                and path.count("/") >= 2:
            return "stage", "/".join(path.split("/")[2:])
        return scope, None

    MEMBER_RUNTIME_MESHES = ((re.compile(r"/mesh_face/CombineFace$"), "Face"),
                             (re.compile(r"/mesh_hair/Hair/[^/]+_Bone\d+$"), "Hair"),
                             (re.compile(r"/mesh_body/Body/[^/]+_Bone\d+$"), "Body"))

    @classmethod
    def member_mesh_alias(cls, path, scope):
        """Editor mesh name of a member renderer the game creates at runtime: LiveCoreMemberHead merges the face
        meshes into CombineFace, and the hair/body SkinnedMeshRenderers are split per bone budget into
        <suit>_head_BoneN / <suit>_body_BoneN below the Hair/Body GameObjects. The editor keeps the source meshes
        (Face, Hair, Body). None when no rule applies."""
        if not isinstance(path, str) or not re.match(r"^member\d+$", scope or ""):
            return None
        for pattern, mesh in cls.MEMBER_RUNTIME_MESHES:
            if pattern.search(path):
                return mesh
        return None

    @staticmethod
    def editor_slot_name(slot):
        """The Unity material name an editor slot stands for: its sourceName, else its name unless the slot is an
        editor-built shader (kind coloring|shader), whose name is the shader or feature name."""
        if slot.get("sourceName"):
            return slot["sourceName"]
        name = slot.get("name") or ""
        shader_name = "/" in name or name.startswith("Native ")
        return None if slot.get("kind") in ("coloring", "shader") and shader_name else slot.get("name")

    @staticmethod
    def editor_relative_path(path):
        """Editor GameObject path below its prefab root (the record root's first node, which the
        game instantiates as the scope root, e.g. the effect prefab root is .../MainStage/Effect)."""
        if not isinstance(path, str):
            return None
        return "/".join(path.split("/")[1:])

    @staticmethod
    def path_suffix(path, suffix):
        """True when `suffix` is the trailing whole-segment part of `path`."""
        return bool(suffix) and isinstance(path, str) and (path == suffix or path.endswith("/" + suffix))

    @classmethod
    def spring_bone_key(cls, path, member_roots):
        """Game swing-bone path -> (editor bone key, None), or (None, (slot, path below Member<N>))
        when the member's BodyPartManager root is unknown; (None, None) outside the members."""
        if not isinstance(path, str):
            return None, None
        for slot, root in sorted((member_roots or {}).items()):
            if root and (path == root or path.startswith(root + "/")):
                return f"member:{slot}:{path[len(root) + 1:]}", None
        match = cls.MEMBER_ROOT.match(path)
        if match:
            return None, (int(match.group(1)), path[match.end():])
        return None, None

    @staticmethod
    def culling_bit(mask, layer):
        """Whether a camera culling mask draws a GameObject layer (signed or unsigned 32-bit mask)."""
        if not isinstance(mask, int) or isinstance(mask, bool) or not isinstance(layer, int) or isinstance(layer, bool) or not 0 <= layer < 32:
            return None
        return bool((mask >> layer) & 1)


# ------------------------------------------------------------------ input

def _gunzip(data):
    return gzip.decompress(data) if data[:2] == b"\x1f\x8b" else data


def is_dump_document(name, value):
    """rtdump-core and rtdump-full are dump documents; the rtdump-probe blob (the game probe's class
    and field inventory) and any other blob are kept aside, never merged."""
    return name != PROBE_BLOB and isinstance(value, dict) and isinstance(value.get("side"), str) and isinstance(value.get("records"), list)


def extract_from_log(text, auxiliary=None):
    """@@RTDUMP dump documents from a job log: strip the GitHub timestamp, verify INDEX bytes and
    sha256. Blobs that are not dump documents go to `auxiliary` (name -> value) when given."""
    index, chunks, done, current = {}, {}, [], None
    for raw in text.splitlines():
        line = TIMESTAMP.sub("", raw)
        if not line.startswith("@@"):
            continue
        if line.startswith("@@RTDUMP-INDEX "):
            entry = json.loads(line[len("@@RTDUMP-INDEX "):])
            index[entry["name"]] = entry
        elif line.startswith("@@RTDUMP-BEGIN "):
            current = line[len("@@RTDUMP-BEGIN "):].strip()
            chunks[current] = []
        elif line.startswith("@@RTDUMP-END "):
            name = line[len("@@RTDUMP-END "):].strip()
            if name != current:
                raise DumpError(f"RTDUMP blob {name} ends while {current} is open")
            done.append(name)
            current = None
        elif current and not line.startswith(("@@RTDUMP-", "@@RTPROBE", "@@SHOT")):
            chunks[current].append(line[2:].strip())
    docs = []
    for name in done:
        blob = base64.b64decode("".join(chunks[name]))
        entry = index.get(name)
        if entry:
            if isinstance(entry.get("bytes"), int) and entry["bytes"] != len(blob):
                raise DumpError(f"RTDUMP {name}: {len(blob)} bytes, index says {entry['bytes']}")
            if entry.get("sha256") and entry["sha256"] != hashlib.sha256(blob).hexdigest():
                raise DumpError(f"RTDUMP {name}: sha256 mismatch")
        value = json.loads(_gunzip(blob).decode("utf-8"))
        if is_dump_document(name, value):
            docs.append(value)
        elif auxiliary is not None:
            auxiliary[name] = value
    if not docs:
        raise DumpError("The job log has no complete @@RTDUMP dump blob.")
    return docs


def merge(docs):
    first = docs[0]
    records = {}
    for doc in docs:
        if doc.get("schema") != first.get("schema") or doc.get("side") != first.get("side"):
            raise DumpError("Dump parts disagree on schema or side.")
        for record in doc.get("records") or []:
            records.setdefault(record.get("id"), record)
    trailers = [doc.get("trailer") for doc in docs if doc.get("trailer")]
    trailer = next((item for item in trailers if item.get("stopReason")), trailers[0] if trailers else None)
    if trailer is not None:
        trailer = dict(trailer, truncation=next((item.get("truncation") for item in trailers if item.get("truncation")),
                                                trailer.get("truncation")))
    ordered = sorted(records.values(), key=lambda record: (record.get("seq") or 0, str(record.get("id"))))
    return {"schema": first.get("schema"), "side": first.get("side"), "header": first.get("header"),
            "records": ordered, "trailer": trailer}


def check_layout(doc):
    conventions = (doc.get("header") or {}).get("conventions") or {}
    if conventions.get("matrixLayout") != "column-major":
        raise DumpError(f"Unsupported matrix layout {conventions.get('matrixLayout')!r}; expected column-major.")
    expected = "unity-lh" if doc.get("side") == "game" else "three-rh-mirror-x"
    if conventions.get("space") != expected:
        raise DumpError(f"A {doc.get('side')} dump must declare space {expected!r}, not {conventions.get('space')!r}.")
    for record in doc["records"]:
        for camera in record.get("cameras") or []:
            projection = camera.get("projection")
            if camera.get("orthographic") or not vector(projection, 16):
                continue
            if abs(projection[11] + 1) > 1e-6 or abs(projection[15]) > 1e-6:
                raise DumpError(f"Record {record.get('id')} {camera.get('key')}: projection e[11]={projection[11]}, "
                                f"e[15]={projection[15]}; a column-major perspective matrix has -1 and 0.")


def load_dump(path):
    """A .json, .json.gz or job-log dump, merged, schema- and layout-checked."""
    raw = Path(path).read_bytes()
    data = _gunzip(raw)
    text = data.decode("utf-8", errors="replace")
    docs, auxiliary = None, {}
    if text.lstrip().startswith("{"):
        try:
            docs = [json.loads(text)]
        except json.JSONDecodeError:
            docs = None
    doc = merge(docs or extract_from_log(text, auxiliary))
    if doc.get("schema") != SCHEMA:
        raise DumpError(f"Unknown dump schema {doc.get('schema')!r}; this comparator reads {SCHEMA}.")
    if doc.get("side") not in ("game", "editor") or not isinstance(doc.get("header"), dict) or not isinstance(doc.get("records"), list):
        raise DumpError("A dump needs side game|editor, a header and records.")
    check_layout(doc)
    doc["_source"] = {"file": str(Path(path).resolve()), "sha256": hashlib.sha256(raw).hexdigest(),
                      "auxiliaryBlobs": sorted(auxiliary)}
    doc["_auxiliary"] = auxiliary
    return doc


# ------------------------------------------------------------------ helpers

def by_key(items):
    return {item.get("key"): item for item in items or [] if isinstance(item, dict) and item.get("key")}


def main_camera(record):
    return by_key(record.get("cameras")).get("camera:main")


def strip_instance(name):
    return Conventions.object_name(name)


def value_of(raw):
    return raw.get("v") if isinstance(raw, dict) and "v" in raw else raw


# Hidden/AS/Member/Main compiles one variant per combination of these keywords;
# every variant samples _MainTex and adds the _RimlightTex rim term.
MEMBER_VARIANT_KEYWORDS = frozenset({"_CHEEK_ON", "_EMISSIVE_ON", "_MATCAP_ON"})
MEMBER_VARIANT_SLOTS = {"_CHEEK_ON": ("_CheekTex",), "_EMISSIVE_ON": ("_EmissiveTex", "_EmissiveScrollTex"),
                        "_MATCAP_ON": ("_MatcapTex", "_MatcapMaskTex")}


def member_sampled_slots(editor_material):
    """Texture slots the AS/Member variant the editor draws samples (empty when it does not report its variant)."""
    if editor_material.get("kind") != "member" or not isinstance(editor_material.get("keywords"), list):
        return set()
    slots = {"_MainTex"}
    if editor_material.get("rimlightEvaluated") is True:
        slots.add("_RimlightTex")
    for keyword in editor_material["keywords"]:
        slots.update(MEMBER_VARIANT_SLOTS.get(keyword, ()))
    return slots


def expected_keys(keys):
    """Expected per-type keys from the bundle-side inventory (12035-runtime-keys.json).

    Renderers are (scope, GameObject path below the prefab root), the same key the
    renderer join uses (schema 1.5)."""
    if not keys:
        return None

    def below_root(path):
        # A renderer on a prefab's own root (e.g. a separate effect prefab such as fx_spo_are_01)
        # keeps its name: the game instantiates that prefab under its scope root.
        return Conventions.editor_relative_path(path) if "/" in path else path
    expected = {"renderers": set(), "stageNodes": set(), "bones": set(), "globals": set()}
    effect = "/EntryPoint/Live/Stages/MainStage/Effect/"
    bindings = [track["binding"][len(effect):] for track in keys.get("tracks", [])
                if track.get("nativeClass") in ("AnimationTrack", "ActivationTrack") and str(track.get("binding", "")).startswith(effect)]
    member_slot = 1
    for prefab, scope in (("prefab:stage", "stage"), ("prefab:effect", "effect")):
        for path, row in (keys.get(prefab) or {}).items():
            if any(component in ("MeshRenderer", "SkinnedMeshRenderer") for component in row.get("components", [])):
                expected["renderers"].add((scope, below_root(path)))
            if prefab == "prefab:effect" and "/" in path:
                inner = path.split("/", 1)[1]
                for binding in bindings:
                    if inner == binding or inner.startswith(binding + "/"):
                        expected["stageNodes"].add(Conventions.stage_node_key(effect + binding, inner[len(binding) + 1:]))
    for prefab in [name for name in keys if name.startswith("prefab:member_")]:
        for path, row in keys[prefab].items():
            if any(component in ("MeshRenderer", "SkinnedMeshRenderer") for component in row.get("components", [])):
                expected["renderers"].add((f"member{member_slot}", below_root(path)))
    for path in (keys.get("member1") or {}).get("bones", []):
        expected["bones"].add(f"member:{member_slot}:{path}")
    expected["globals"] = {f"global:{name}" for name in keys.get("shaderGlobalCandidates", [])}
    return expected


# ------------------------------------------------------------------ comparison

class Comparison:
    def __init__(self, game, editor, tolerances=None, phase="auto", keys=None):
        if editor.get("side") != "editor":
            raise DumpError("--editor must be an editor dump (side editor).")
        self.game, self.editor = game, editor
        self.tol = dict(DEFAULT_TOLERANCES, **(tolerances or {}))
        self.identity = game.get("side") == "editor"
        self.requested_phase = phase
        self.keys = keys
        self.items = []
        self.notes = defaultdict(list)
        self.renderer_map, self.ambiguous, self.components = {}, set(), {}
        self.ambiguous_candidates = set()
        self.joins = {}                      # game renderer key -> (editor key | None, method)
        self.join_methods = Counter()
        self.game_renderers = {}             # game renderer key -> (scope, relative path)
        self.coverage_sets = defaultdict(lambda: {"game": set(), "editor": set()})
        self.blend_coverage = Counter()
        self.editor_index = {}
        for record in editor["records"]:
            if self.identity:
                self.editor_index[record.get("id")] = record
            else:
                self.editor_index[(record.get("sourceRecord"), record.get("phase"))] = record
        self.member_roots = self._member_roots()
        self.performer_mismatch = {}
        self.culling_masks = self._culling_masks()
        self.editor_catalog = self._editor_catalog()
        self.axis_billboards = self._axis_billboards()

    # -- game- and editor-wide context
    def _member_roots(self):
        """Slot -> the member's BodyPartManager GameObject path (members part rootPath)."""
        roots = {}
        for record in self.game["records"]:
            for member in record.get("members") or [] if record.get("part") == "members" else []:
                if isinstance(member, dict) and isinstance(member.get("slot"), int) and isinstance(member.get("rootPath"), str):
                    roots.setdefault(member["slot"], member["rootPath"])
        return roots

    def _culling_masks(self):
        """(directorTime, seq, main camera cullingMask, other enabled cameras' masks) per game frame record."""
        masks = []
        for record in self.game["records"]:
            if record.get("kind") != "frame" or not number((record.get("clock") or {}).get("directorTime")):
                continue
            camera = main_camera(record) or {}
            others = {item.get("key"): item.get("cullingMask") for item in record.get("cameras") or []
                      if isinstance(item, dict) and item.get("key") != "camera:main" and item.get("isActiveAndEnabled", item.get("enabled")) is True
                      and isinstance(item.get("cullingMask"), int)}
            masks.append((record["clock"]["directorTime"], record.get("seq") or 0, camera.get("cullingMask"), others))
        return sorted(masks, key=lambda item: (item[0], item[1]))

    def culling_mask(self, record):
        """The main camera culling mask of the game frame record nearest in director time."""
        t = (record.get("clock") or {}).get("directorTime")
        if not self.culling_masks or not number(t):
            return None, {}
        cache = self.__dict__.setdefault("_mask_cache", {})
        ident = (record.get("id"), t)
        if ident not in cache:
            best = min(self.culling_masks, key=lambda item: (abs(item[0] - t), abs((item[1] or 0) - (record.get("seq") or 0))))
            cache[ident] = (best[2], best[3])
        return cache[ident]

    def _axis_billboards(self):
        """GameObject paths below the stage effect root that carry an AxisBillboard (the keys' serialized
        prefab:effect components). LiveCoreStageEffect.Initialize collects them with
        GetComponentsInChildren<AxisBillboard>(true) on its own GameObject (0x2f6f554-0x2f6f568), so only rows at or
        below a row that lists LiveCoreStageEffect count. The other prefab:effect roots (12035: fx_spo_are_01,
        fx_spo_sha_01, fx_spo_sha_02) are not the Effect GameObject either; a billboard there never gets camera
        targets (AxisBillboard.Initialize 0x27bff10 enables it only with targets) and keeps its full rotation."""
        rows = (self.keys or {}).get("prefab:effect") or {}
        components = {path: (row or {}).get("components") or [] for path, row in rows.items()}
        effects = {path for path, names in components.items() if STAGE_EFFECT_CLASS in names}

        def below_effect(path):
            parts = path.split("/")
            return any("/".join(parts[:end]) in effects for end in range(1, len(parts) + 1))

        return {Conventions.editor_relative_path(path) for path, names in components.items()
                if "/" in path and AXIS_BILLBOARD_CLASS in names and below_effect(path)}

    def axis_billboard_role(self, path):
        """'self' when the effect GameObject at the game path carries an AxisBillboard, 'below' when an ancestor
        does, else None."""
        if not self.axis_billboards or not isinstance(path, str) or not Conventions.SCOPE_ROOTS[0][1].match(path):
            return None
        parts = Conventions.game_relative_path(path, "effect").split("/")
        if "/".join(parts) in self.axis_billboards:
            return "self"
        return "below" if any("/".join(parts[:end]) in self.axis_billboards for end in range(1, len(parts))) else None

    def compare_billboard_transform(self, prefix, key, record, game, editor, role, near, field=None):
        """Transform of an AxisBillboard node whose turn is draw history (see AXIS_BILLBOARD_CLASS): position,
        scale and the up axis for the billboard itself; only scale below it (the turn moves its children)."""
        game, editor = dict(game), dict(editor)
        rotations = (game.pop("rotation", None), editor.pop("rotation", None))
        if role == "below":
            game.pop("position", None)
            editor.pop("position", None)
        self.compare_transform("transforms", prefix, key, record, game, editor, self.tol["stagePositionM"],
                               self.tol["stageRotationDeg"], near, field)
        if role == "self" and vector(rotations[0], 4) and vector(rotations[1], 4):
            converted = self.quat(rotations[1])
            self.add("transforms", prefix + "UpAxisDeg", key, record, rotations[0], converted, axis_angle(rotations[0], converted),
                     self.tol["stageRotationDeg"], near_cut=near, field=f"{field} (AxisBillboard up axis)" if field else "AxisBillboard up axis")

    def _editor_catalog(self):
        """Every editor renderer (renderers parts and census) by key: scope, mesh, GameObject path."""
        catalog = {}
        for record in self.editor["records"]:
            entries = [dict(item) for item in record.get("renderers") or [] if isinstance(item, dict)]
            entries += [dict(node) for node in (record.get("census") or {}).get("nodes") or []
                        if isinstance(node, dict) and node.get("kind") == "renderer"]
            for entry in entries:
                key = entry.get("key")
                if not key or key in catalog:
                    continue
                if not entry.get("scope") or "mesh" not in entry:
                    parsed = Conventions.renderer_scope_mesh(key)
                    if parsed:
                        entry.setdefault("scope", parsed[0])
                        entry.setdefault("mesh", parsed[1])
                catalog[key] = {"key": key, "scope": entry.get("scope"), "mesh": entry.get("mesh"), "path": entry.get("path"),
                                "relative": Conventions.editor_relative_path(entry.get("path"))}
        return catalog

    # -- items
    def add(self, type_, metric, key, record, game_value, editor_value, error, tol, exact=False, near_cut=False, field=None):
        if error is None:
            return
        if exact:
            score = EXACT_SCORE if error else 0.0
        else:
            score = error / tol if tol > 0 else (0.0 if error == 0 else EXACT_SCORE)
        self.items.append({"type": type_, "metric": metric, "key": key, "field": field, "t": (record.get("clock") or {}).get("directorTime"),
                           "record": record.get("id"), "game": game_value, "editorConverted": editor_value,
                           "error": error, "tol": tol if not exact else "exact", "score": score, "nearCut": bool(near_cut)})

    # -- conversion wrappers (identity mode skips them)
    def pos(self, p):
        return list(p) if self.identity else Conventions.position(p)

    def quat(self, q):
        return list(q) if self.identity else Conventions.quaternion(q)

    def partner(self, record, phase):
        if self.identity:
            return self.editor_index.get(record.get("id"))
        return self.editor_index.get((record.get("id"), phase))

    # -- timing
    def calibrate(self, frames):
        tol = self.tol
        phases = sorted({key[1] for key in self.editor_index}) if not self.identity else [0]
        result = {"mode": "identity" if self.identity else "calibrated", "candidates": phases}
        if self.identity:
            result.update(chosen=0, method="identity")
            return result
        residuals, histogram = defaultdict(dict), Counter()
        for record in frames:
            game_camera = main_camera(record)
            if not game_camera or not vector((game_camera.get("rig") or {}).get("position"), 3):
                continue
            best = None
            for phase in phases:
                partner = self.partner(record, phase)
                editor_camera = main_camera(partner) if partner else None
                if not editor_camera or not editor_camera.get("liveShot", True) or not vector((editor_camera.get("transform") or {}).get("position"), 3):
                    continue
                rig = game_camera["rig"]
                delta_p = [(g - e) / tol["cameraPositionM"] for g, e in zip(rig["position"], self.pos(editor_camera["transform"]["position"]))]
                delta_r = [value / tol["cameraRotationDeg"] for value in qlog_deg(rig["rotation"], self.quat(editor_camera["transform"]["rotation"]))] \
                    if vector(rig.get("rotation"), 4) else [0.0, 0.0, 0.0]
                delta_f = [(game_camera.get("fieldOfView", 0) - editor_camera.get("fieldOfView", 0)) / tol["fovDeg"]]
                vec = delta_p + delta_r + delta_f
                residuals[record["id"]][phase] = vec
                score = math.sqrt(sum(value * value for value in vec))
                if best is None or score < best[0] - 1e-12 or (abs(score - best[0]) <= 1e-12 and abs(phase) < abs(best[1])):
                    best = (score, phase)
            if best:
                histogram[best[1]] += 1
        result["histogram"] = {str(phase): histogram.get(phase, 0) for phase in phases}
        complete = [rid for rid, values in residuals.items() if all(phase in values for phase in phases)]
        # A constant offset (a moved camera, a FoV bias) pulls the per-record
        # best phase toward whichever neighbour cancels it; the residual spread
        # around its mean is immune to that. It is only informative when the
        # camera speed varies between records, so it decides only when clear.
        costs, decisive = {}, False
        if len(complete) >= 3:
            for phase in phases:
                vectors = [residuals[rid][phase] for rid in complete]
                mean = [statistics.fmean(column) for column in zip(*vectors)]
                costs[phase] = sum(sum((value - mu) ** 2 for value, mu in zip(vec, mean)) for vec in vectors)
            ranked = sorted(phases, key=lambda phase: (costs[phase], abs(phase)))
            decisive = len(ranked) > 1 and costs[ranked[1]] > 1e-6 * len(complete) and costs[ranked[0]] <= 0.25 * costs[ranked[1]]
        if decisive:
            chosen = ranked[0]
            method = "bias-invariant pose residual over frame records"
        elif histogram:
            chosen = max(phases, key=lambda phase: (histogram.get(phase, 0), -abs(phase)))
            method = "mode of per-record best phase"
        else:
            chosen, method = 0, "default (no comparable camera)"
        result.update(chosen=chosen, method=method, costs={str(key): value for key, value in costs.items()}, records=len(residuals))
        if self.requested_phase not in (None, "auto"):
            result.update(chosen=int(self.requested_phase), method="override", calibrated=chosen)
        return result

    def calibrate_globals(self, frames):
        """Shader time globals are written for the frame being set up (game _MusicTime == clock.directorTime) while
        transforms show the previous evaluation: calibrate their own phase on _MusicTime, default 0."""
        if self.identity:
            return 0
        phases = sorted({key[1] for key in self.editor_index})
        errors = defaultdict(list)
        for record in frames:
            game = (record.get("globals") or {}).get("global:_MusicTime")
            for phase in phases:
                partner = self.partner(record, phase)
                editor = ((partner or {}).get("globals") or {}).get("global:_MusicTime")
                if isinstance(game, dict) and isinstance(editor, dict) and number(game.get("f")) and number(editor.get("f")):
                    errors[phase].append(abs(game["f"] - editor["f"]))
        if not errors:
            return 0
        return min(errors, key=lambda phase: (statistics.median(errors[phase]), abs(phase)))

    def compare_member_identity(self, record, partner):
        """The editor must dress each slot as the game did (frame members[].suitId vs editor costumeId)."""
        editor = {item.get("slot"): item for item in partner.get("members") or [] if isinstance(item, dict)}
        for member in record.get("members") or []:
            other = editor.get(member.get("slot"))
            if not other or not isinstance(member.get("suitId"), int):
                continue
            if member.get("memberId") != other.get("memberId") or member["suitId"] != other.get("costumeId"):
                self.performer_mismatch[member.get("slot")] = {"game": {"memberId": member.get("memberId"), "suitId": member["suitId"]},
                                                               "editor": {"memberId": other.get("memberId"), "costumeId": other.get("costumeId")}}

    def cuts(self, phase):
        values = set()
        for record in self.game["records"]:
            if record.get("kind") != "frame":
                continue
            partner = self.partner(record, phase)
            camera = main_camera(partner) if partner else None
            event = (camera or {}).get("event")
            if event and number(event.get("start")) and number(event.get("duration")):
                values.update((event["start"], event["start"] + event["duration"]))
        return sorted(values)

    def timing_uncertain(self, record, phase):
        """Any record (frame or full part) whose Time.deltaTime was clamped to maximumDeltaTime while the director
        followed the music clock: the pose phase t + phase * deltaTime is not the neighbouring frame's time, so the
        record is timing-uncertain at every phase but 0, unless the editor evaluated that phase at the director time the
        dump recorded for the neighbouring frame (clock.phaseSource "recorded"). Each record is noted once."""
        dt = (record.get("clock") or {}).get("deltaTime")
        if self.identity or phase == 0 or not number(dt) or dt < MAX_DELTA_TIME - 1e-6:
            return False
        partner = self.partner(record, phase)
        if ((partner or {}).get("clock") or {}).get("phaseSource") == "recorded":
            return False
        if record.get("id") not in self.notes["timing.clampedDeltaTime"]:
            self.notes["timing.clampedDeltaTime"].append(record.get("id"))
        return True

    def near_cut(self, record, phase, cuts):
        clock = record.get("clock") or {}
        t, dt = clock.get("directorTime"), clock.get("deltaTime") or 1 / 30
        if self.timing_uncertain(record, phase):
            return True
        if number(t) and any(abs(t - cut) <= dt + 1e-9 for cut in cuts):
            return True
        if record.get("kind") == "frame" and not self.identity:
            events = []
            for candidate in (phase - 1, phase, phase + 1):
                partner = self.partner(record, candidate)
                camera = main_camera(partner) if partner else None
                if camera and camera.get("event"):
                    events.append((camera["event"].get("track"), camera["event"].get("start")))
            return len(set(events)) > 1
        return False

    # -- per asset type
    def compare_camera(self, record, partner, near, hypotheses):
        tol = self.tol
        game_camera, editor_camera = main_camera(record), main_camera(partner)
        if not game_camera or not editor_camera:
            self.notes["camera"].append(f"{record['id']}: main camera missing on {'game' if not game_camera else 'editor'} side")
            return
        if editor_camera.get("liveShot") is False:
            self.notes["camera"].append(f"{record['id']}: the editor has no live shot at t={record['clock'].get('directorTime')}")
            return
        key = "camera:main"
        if number(game_camera.get("fieldOfView")) and number(editor_camera.get("fieldOfView")):
            error = abs(game_camera["fieldOfView"] - editor_camera["fieldOfView"])
            self.add("camera", "fovAbsDeg", key, record, game_camera["fieldOfView"], editor_camera["fieldOfView"], error, tol["fovDeg"], near_cut=near)
        if number(game_camera.get("aspect")) and number(editor_camera.get("aspect")):
            error = abs(game_camera["aspect"] - editor_camera["aspect"]) / abs(editor_camera["aspect"])
            self.add("camera", "aspectRel", key, record, game_camera["aspect"], editor_camera["aspect"], error, tol["aspectRel"], near_cut=near)
        if vector(game_camera.get("projection"), 16) and vector(editor_camera.get("projection"), 16):
            worst = (0.0, 0, 0.0)
            for index, (g, e) in enumerate(zip(game_camera["projection"], editor_camera["projection"])):
                if abs(e) < 1e-9:
                    score = abs(g - e) / tol["projectionZeroAbs"]
                    error = abs(g - e)
                else:
                    error = abs(g - e) / abs(e)
                    score = error / tol["projectionRel"]
                if score > worst[0]:
                    worst = (score, index, error)
            self.add("camera", "projectionMaxRel", key, record, game_camera["projection"][worst[1]], editor_camera["projection"][worst[1]],
                     worst[0], 1.0, near_cut=near, field=f"e[{worst[1]}] (error {worst[2]:.3g})")
        for name, metric, tol_key, relative in (("nearClipPlane", "nearAbs", "nearAbs", False), ("farClipPlane", "farRel", "farRel", True)):
            if number(game_camera.get(name)) and number(editor_camera.get(name)):
                error = abs(game_camera[name] - editor_camera[name]) / (abs(editor_camera[name]) if relative else 1)
                self.add("camera", metric, key, record, game_camera[name], editor_camera[name], error, tol[tol_key], near_cut=near)
        # An editor document used as the game side has no separate rig: its camera transform is the rig.
        rig = (game_camera.get("transform") if self.identity else game_camera.get("rig")) or {}
        editor_transform = editor_camera.get("transform") or {}
        rig_rotation = None
        if vector(rig.get("position"), 3) and vector(editor_transform.get("position"), 3):
            converted = self.pos(editor_transform["position"])
            self.add("camera", "rigPositionM", key, record, rig["position"], converted, distance(rig["position"], converted),
                     tol["cameraPositionM"], near_cut=near)
        if vector(rig.get("rotation"), 4) and vector(editor_transform.get("rotation"), 4):
            rig_rotation = self.quat(editor_transform["rotation"])
            self.add("camera", "rigRotationDeg", key, record, rig["rotation"], rig_rotation, qangle(rig["rotation"], rig_rotation),
                     tol["cameraRotationDeg"], near_cut=near)
        if vector(game_camera.get("worldToCamera"), 16) and vector(editor_camera.get("worldToCamera"), 16):
            errors = {}
            for hypothesis in (Conventions.HYPOTHESES if not self.identity else ("identity",)):
                expected = editor_camera["worldToCamera"] if self.identity else Conventions.world_to_camera(editor_camera["worldToCamera"], hypothesis)
                deltas = [abs(g - e) for g, e in zip(game_camera["worldToCamera"], expected)]
                errors[hypothesis] = (max(delta for index, delta in enumerate(deltas) if index not in W2C_TRANSLATION),
                                      max(deltas[index] for index in W2C_TRANSLATION))
            hypotheses.append((record, near, errors))
        component = (game_camera.get("transform") or {}).get("rotation")
        if vector(component, 4) and rig_rotation is not None:
            hypotheses_rotations = {name: (Conventions.camera_component_rotation(rig_rotation, name) if not self.identity else rig_rotation)
                                    for name in (Conventions.HYPOTHESES if not self.identity else ("identity",))}
            self.components[record.get("id")] = (component, hypotheses_rotations)
        self.compare_anchors(record, partner, game_camera, editor_camera, near)
        game_splits = {k: v for k, v in by_key(record.get("cameras")).items() if k.startswith("camera:split")}
        editor_splits = by_key(partner.get("cameras"))
        for split_key, game_split in game_splits.items():
            editor_split = editor_splits.get(split_key)
            if editor_split and number(game_split.get("fieldOfView")) and number(editor_split.get("fieldOfView")):
                self.add("camera", "splitFovAbsDeg", split_key, record, game_split["fieldOfView"], editor_split["fieldOfView"],
                         abs(game_split["fieldOfView"] - editor_split["fieldOfView"]), tol["fovDeg"], near_cut=near)

    def compare_anchors(self, record, partner, game_camera, editor_camera, near):
        game_anchors, editor_anchors = by_key(record.get("anchors")), by_key(partner.get("anchors"))
        if not all(vector(camera.get(name), 16) for camera in (game_camera, editor_camera) for name in ("projection", "worldToCamera")):
            return
        worst_pose = worst_camera = None
        for key, game_anchor in game_anchors.items():
            editor_anchor = editor_anchors.get(key)
            if not editor_anchor or not vector(game_anchor.get("position"), 3) or not vector(editor_anchor.get("position"), 3):
                continue
            gg = project(game_camera["projection"], game_camera["worldToCamera"], game_anchor["position"])
            ee = project(editor_camera["projection"], editor_camera["worldToCamera"], editor_anchor["position"])
            ge = project(editor_camera["projection"], editor_camera["worldToCamera"], self.pos(game_anchor["position"]))
            if gg is None or ee is None or ge is None:
                continue
            pose = max(abs(gg[0] - ee[0]), abs(gg[1] - ee[1]))
            cam = max(abs(gg[0] - ge[0]), abs(gg[1] - ge[1]))
            if worst_pose is None or pose > worst_pose[0]:
                worst_pose = (pose, key, gg[:2], ee[:2])
            if worst_camera is None or cam > worst_camera[0]:
                worst_camera = (cam, key, gg[:2], ge[:2])
        if worst_pose:
            self.add("camera", "anchorNdcMax", worst_pose[1], record, worst_pose[2], worst_pose[3], worst_pose[0], self.tol["ndc"], near_cut=near,
                     field="game anchor/game camera vs editor anchor/editor camera")
        if worst_camera:
            self.add("camera", "anchorNdcCameraOnly", worst_camera[1], record, worst_camera[2], worst_camera[3], worst_camera[0], self.tol["ndc"],
                     near_cut=near, field="game anchor through game vs editor camera")

    def compare_aspect(self, record, partner, near):
        game_corrector = by_key(record.get("correctors")).get("corrector:camera:main")
        editor_corrector = by_key(partner.get("correctors")).get("corrector:camera:main")
        if game_corrector and editor_corrector and number(game_corrector.get("correction")) and number(editor_corrector.get("correction")):
            self.add("aspect", "correctionAbs", "corrector:camera:main", record, game_corrector["correction"], editor_corrector["correction"],
                     abs(game_corrector["correction"] - editor_corrector["correction"]), self.tol["correction"], near_cut=near)

    def compare_globals(self, record, partner, near):
        game_globals, editor_globals = record.get("globals") or {}, partner.get("globals") or {}
        dt = (record.get("clock") or {}).get("deltaTime") or 1 / 30
        for key, editor_value in editor_globals.items():
            game_value = game_globals.get(key)
            if not isinstance(editor_value, dict) or not number(editor_value.get("f")):
                if isinstance(game_value, dict):
                    self.notes["globals.gameOnly"].append(key)
                continue
            if editor_value.get("perMaterial") is True or str(editor_value.get("from") or "").endswith("(per material)"):
                # e.g. _SelfTime: LiveColoringTrack clip-local time on one editor material, not a shader global.
                game_f = game_value.get("f") if isinstance(game_value, dict) else None
                self.notes["globals.perMaterial"].append(f"{key} editor {editor_value.get('from')} is per material; game global "
                                                         f"{'set' if number(game_f) and game_f != 0 else 'unset/0'}")
                continue
            if not isinstance(game_value, dict) or not number(game_value.get("f")):
                self.notes["globals.editorOnly"].append(key)
                continue
            name = key.split(":", 1)[1]
            if name in VECTOR_GLOBALS and vector(game_value.get("v")) and vector(editor_value.get("v")) \
                    and min(len(game_value["v"]), len(editor_value["v"])) >= 2:
                # Render-target size in pixels: exact.
                error = max(abs(game_value["v"][index] - editor_value["v"][index]) for index in range(2))
                self.add("globals", "globalVector", key, record, game_value["v"][:2], editor_value["v"][:2], int(error > 0), 0,
                         exact=True, near_cut=near, field=editor_value.get("from"))
                continue
            tol = max(self.tol["globalAbs"], dt) if name in TIME_GLOBALS else (self.tol["beatAbs"] or self.tol["globalAbs"]) if name in BEAT_GLOBALS else self.tol["globalAbs"]
            self.add("globals", "globalAbs", key, record, game_value["f"], editor_value["f"], abs(game_value["f"] - editor_value["f"]), tol,
                     near_cut=near, field=editor_value.get("from"))

    def compare_transform(self, type_, prefix, key, record, game, editor, tol_position, tol_rotation, near, field=None):
        if vector(game.get("position"), 3) and vector(editor.get("position"), 3):
            converted = self.pos(editor["position"])
            self.add(type_, prefix + "PositionM", key, record, game["position"], converted, distance(game["position"], converted), tol_position,
                     near_cut=near, field=field)
        if vector(game.get("rotation"), 4) and vector(editor.get("rotation"), 4):
            converted = self.quat(editor["rotation"])
            self.add(type_, prefix + "RotationDeg", key, record, game["rotation"], converted, qangle(game["rotation"], converted), tol_rotation,
                     near_cut=near, field=field)
        if vector(game.get("lossyScale"), 3) and vector(editor.get("lossyScale"), 3):
            error = max(abs(g - e) / max(abs(e), 1e-9) for g, e in zip(game["lossyScale"], editor["lossyScale"]))
            self.add(type_, prefix + "ScaleRel", key, record, game["lossyScale"], editor["lossyScale"], error, self.tol["scaleRel"],
                     near_cut=near, field=field)

    def join_renderer(self, game_renderer):
        """Editor key of a game renderer on (scope, GameObject path), schema 1.5:

        1. path: the game path below its scope root equals the editor path below its prefab root;
        2. pathSuffix: the editor path below its prefab root is the unique longest trailing part of
           the game path (absorbs scope-root containers such as MainStage/Model);
        3. mesh: only an editor renderer the server flattened (no GameObject chain in the glTF,
           path null) can join on its mesh name, and only when it is unique in the scope.
        Mesh names never override a path: on a path join they are only checked (note)."""
        key = game_renderer.get("key")
        if key in self.joins:
            return self.joins[key][0]
        scope = game_renderer.get("scope")
        relative = Conventions.game_relative_path(game_renderer.get("path"), scope, self.member_roots)
        rescoped, below = Conventions.game_scope(game_renderer.get("path"), scope)
        if rescoped != scope:
            self.notes["renderers.stageSceneRoot"].append(f"{game_renderer.get('path')} -> {rescoped}:{below}")
            scope, relative = rescoped, below
        self.game_renderers[key] = (scope, relative)
        if not self.identity and game_renderer.get("mesh") is None and str(game_renderer.get("class", "")).endswith(".MeshRenderer"):
            # A MeshRenderer whose MeshFilter has no mesh draws nothing (e.g. litD_* in 12035: m_Mesh PathID 0).
            self.notes["renderers.gameNullMesh"].append(relative)
            self.joins[key] = (None, "gameNullMesh")
            self.join_methods["gameNullMesh"] += 1
            return None
        same_scope = [entry for entry in self.editor_catalog.values() if entry["scope"] == scope]
        result = (None, "none")
        if self.identity:
            result = (key, "identity") if key in self.editor_catalog else (None, "none")
        else:
            exact = [entry["key"] for entry in same_scope if entry["relative"] is not None and relative is not None and entry["relative"] == relative]
            suffix = sorted(((len(entry["relative"]), entry["key"]) for entry in same_scope
                             if entry["relative"] and Conventions.path_suffix(relative, entry["relative"])), reverse=True)
            flattened = [entry["key"] for entry in same_scope if entry["path"] is None and game_renderer.get("mesh") is not None
                         and Conventions.object_name(entry["mesh"]) == Conventions.object_name(game_renderer.get("mesh"))]
            alias = Conventions.member_mesh_alias(game_renderer.get("path"), scope)
            if not flattened and alias:
                flattened = [entry["key"] for entry in same_scope if entry["path"] is None and entry["mesh"] == alias]
                if len(flattened) == 1:
                    self.notes["renderers.memberRuntimeMesh"].append(f"{game_renderer.get('mesh')} -> {alias}")
            if len(exact) == 1:
                result = (exact[0], "path")
            elif len(exact) > 1:
                result = (None, "ambiguous")
                self.ambiguous_candidates.update(exact)
            elif suffix:
                longest = [item for item in suffix if item[0] == suffix[0][0]]
                if len(longest) == 1:
                    result = (longest[0][1], "pathSuffix")
                else:
                    result = (None, "ambiguous")
                    self.ambiguous_candidates.update(item[1] for item in longest)
            elif len(flattened) == 1:
                result = (flattened[0], "mesh")
            elif len(flattened) > 1:
                result = (None, "ambiguous")
                self.ambiguous_candidates.update(flattened)
        if result[1] == "ambiguous":
            self.ambiguous.add(key)
        self.joins[key] = result
        self.join_methods[result[1]] += 1
        if result[0]:
            self.renderer_map[key] = result[0]
            editor_mesh = self.editor_catalog[result[0]]["mesh"]
            if result[1] in ("path", "pathSuffix") and game_renderer.get("mesh") is not None and \
                    Conventions.object_name(editor_mesh) != Conventions.object_name(game_renderer.get("mesh")):
                self.notes["renderers.meshCheck"].append(f"{relative}: game mesh {game_renderer.get('mesh')!r}, editor {editor_mesh!r}")
        return result[0]

    def game_drawn(self, renderer, record):
        """(drawn, explanation) of a game renderer for the main camera (contract 1):
        enabled && activeInHierarchy && ((mainCamera.cullingMask >> layer) & 1)."""
        if self.identity:
            visible, culled = renderer.get("visible"), renderer.get("culled") is True
            return (visible and not culled) if isinstance(visible, bool) else None, None
        enabled = renderer.get("enabled", True) is not False
        active = renderer.get("activeInHierarchy", True) is not False
        mask, others = self.culling_mask(record)
        layer = renderer.get("layer")
        bit = Conventions.culling_bit(mask, layer)
        if bit is None:
            self.notes["visibility.layerUnknown"].append("layer or main camera cullingMask missing; drawn = enabled && active")
            return enabled and active, f"enabled={enabled} active={active} layer={layer} mask=?"
        picture = False
        if not bit and enabled and active:
            drawn_by = sorted(name for name, other in others.items() if Conventions.culling_bit(other, layer))
            if drawn_by:
                self.notes["visibility.otherCameraLayers"].append(f"layer {layer} excluded by camera:main, included by {', '.join(drawn_by)}")
            picture = any(name in PICTURE_CAMERAS for name in drawn_by)
            if picture:
                self.notes["visibility.overlayCamera"].append(f"layer {layer} drawn by the overlay camera")
        return enabled and active and (bit or picture), \
            f"enabled={enabled} active={active} layer={layer} mainMaskBit={int(bit)}" + (" overlayCamera=1" if picture else "")

    def compare_renderers(self, record, partner, near):
        editor_renderers = by_key(partner.get("renderers"))
        for game_renderer in record.get("renderers") or []:
            key = game_renderer.get("key")
            match = self.join_renderer(game_renderer)
            if match is None:
                continue
            editor_renderer = editor_renderers.get(match)
            if editor_renderer is None:
                self.notes["renderers.notInEditorRecord"].append(match)
                continue
            game_visible, why = self.game_drawn(game_renderer, record)
            editor_visible = editor_renderer.get("visible")
            material_hidden = False
            if isinstance(editor_visible, bool):
                # An editor renderer is drawn only when its node is visible and not culled and its materials are
                # visible (three.js skips a mesh whose material.visible is false).
                editor_visible = editor_visible and editor_renderer.get("culled") is not True
                material_hidden = editor_visible and editor_renderer.get("materialVisible") is False
                editor_visible = editor_visible and not material_hidden
            if isinstance(game_visible, bool) and isinstance(editor_visible, bool):
                if game_visible and material_hidden and not self.identity:
                    # The editor hides materials whose draw adds nothing (coloring tint alpha 0, a penlight without
                    # clip input) while the game still draws them: the materials comparison checks the game's draw
                    # adds nothing either (hidden material tint), so the renderer is not scored here.
                    if match not in self.notes["visibility.materialHidden"]:
                        self.notes["visibility.materialHidden"].append(match)
                else:
                    editor_why = (f"visible={editor_renderer.get('visible')} culled={editor_renderer.get('culled') is True} "
                                  f"materialVisible={editor_renderer.get('materialVisible')}")
                    self.add("visibility", "rendererVisible", key, record, game_visible, editor_visible,
                             int(game_visible != editor_visible), 0, exact=True, near_cut=near,
                             field=f"{match} ({self.joins[key][1]}; game {why}; editor {editor_why})" if why else match)
            billboard_offscreen = (not self.identity and editor_renderer.get("axisBillboard") is True
                                   and game_renderer.get("isVisible") is False)
            if billboard_offscreen:
                # AxisBillboard turns a node only while a camera renders it: an off-screen game cone keeps the
                # rotation of the last frame it was drawn in, while the editor reports the live camera's turn.
                self.notes["transforms.offscreenAxisBillboard"].append(match)
            if not self.identity and self.editor_catalog.get(match, {}).get("path") is None:
                # The server baked this renderer's node transform into its vertices: the editor transform is identity.
                self.notes["transforms.flattenedEditor"].append(match)
            else:
                game_transform = dict(game_renderer.get("transform") or {})
                editor_transform = dict(editor_renderer.get("transform") or {})
                role = self.axis_billboard_role(game_renderer.get("path")) if billboard_offscreen else None
                if role:
                    self.compare_billboard_transform("renderer", key, record, game_transform, editor_transform, role, near)
                else:
                    if billboard_offscreen:
                        game_transform.pop("rotation", None)
                        editor_transform.pop("rotation", None)
                    self.compare_transform("transforms", "renderer", key, record, game_transform,
                                           editor_transform, self.tol["stagePositionM"], self.tol["stageRotationDeg"], near)
            editor_slots = {item.get("slot"): item for item in editor_renderer.get("materials") or []}
            for slot in game_renderer.get("materials") or []:
                editor_slot = editor_slots.get(slot.get("slot"))
                editor_name = (editor_slot.get("name") if self.identity else Conventions.editor_slot_name(editor_slot)) if editor_slot else None
                if editor_slot and slot.get("name") and not editor_name:
                    self.notes["materials.editorShaderSlot"].append(f"{editor_slot.get('kind')}:{editor_slot.get('name')} for {slot['name']}")
                if editor_slot and slot.get("name") and editor_name:
                    same = Conventions.object_name(slot["name"]) == Conventions.object_name(editor_name)
                    self.add("materials", "slotName", f"{key}#{slot.get('slot')}", record, slot["name"], editor_name, int(not same), 0,
                             exact=True, near_cut=near)
                    # The game reads Material.shaderKeywords per renderer slot: the drawn AS/Member variant
                    # (_CHEEK_ON among them) is compared there.
                    if same:
                        self.compare_member_variant(f"material:{key}#{slot.get('slot')}", record, slot, editor_slot, near)
            if number(game_renderer.get("isVisible")) or isinstance(game_renderer.get("isVisible"), bool):
                self.notes["visibility.isVisible"].append(bool(game_renderer["isVisible"]))

    def compare_property(self, key, name, record, game_property, editor_property, near, sampled=False):
        kind = game_property.get("t")
        game_value, editor_value = game_property.get("v"), editor_property.get("v")
        if kind == "tex" or editor_property.get("t") == "tex":
            if isinstance(editor_value, dict) and editor_value.get("placeholder") is True:
                if sampled and isinstance(game_value, dict) and (game_value.get("name") or game_value.get("width")):
                    # The variant the editor draws samples this slot, the game binds a real texture
                    # and the editor only its 1x1 constant: the texture is missing from the import.
                    self.add("materials", "textureMissing", key, record, game_value, editor_value, 1, 0, exact=True,
                             near_cut=near, field=name)
                else:
                    # The editor's 1x1 constant bound where it has no texture: not a Unity texture, never scored.
                    self.notes["materials.placeholderTextures"].append(
                        f"{name}: game {(game_value or {}).get('name') if isinstance(game_value, dict) else game_value!r}")
            elif isinstance(game_value, dict) and isinstance(editor_value, dict):
                same = all(game_value.get(field) == editor_value.get(field) for field in ("width", "height")
                           if game_value.get(field) is not None and editor_value.get(field) is not None)
                self.add("materials", "textureSize", key, record, game_value, editor_value, int(not same), 0, exact=True, near_cut=near, field=name)
                game_mips = game_value.get("mipCount", game_value.get("mips"))
                if isinstance(game_mips, int) and isinstance(editor_value.get("mips"), int):
                    if editor_value.get("mipsGenerated") is True:
                        # The GPU built the editor's chain: authored mips were not uploaded, so the
                        # count says nothing about the asset's levels. Noted, never scored.
                        self.notes["materials.generatedMips"].append(
                            f"{name}: game {game_mips} authored, editor {editor_value['mips']} generated (authored mips not uploaded)")
                    else:
                        self.add("materials", "textureMips", key, record, game_mips, editor_value["mips"],
                                 int(game_mips != editor_value["mips"]), 0, exact=True, near_cut=near, field=name)
                game_name, editor_name = game_value.get("name"), editor_value.get("name")
                if game_name and editor_name and Conventions.object_name(game_name) != Conventions.object_name(editor_name):
                    self.notes["materials.textureNames"].append(f"{name}: game {game_name!r}, editor {editor_name!r}")
            elif isinstance(editor_value, dict) and game_value is None:
                self.notes["materials.textureOnlyInEditor"].append(name)
            if vector(game_property.get("st"), 4) and vector(editor_property.get("st"), 4):
                editor_st = editor_property["st"]
                if not self.identity and editor_property.get("stFrom") in Conventions.V_FLIPPED_ST:
                    editor_st = Conventions.texture_st(editor_st)
                error = max(abs(g - e) for g, e in zip(game_property["st"], editor_st))
                self.add("materials", "textureStAbs", key, record, game_property["st"], editor_st, error, self.tol["stAbs"],
                         near_cut=near, field=name)
            return
        if number(game_value):
            game_value = [game_value]
        if number(editor_value):
            editor_value = [editor_value]
        if not vector(game_value) or not vector(editor_value):
            return
        count = min(len(game_value), len(editor_value))
        if kind == "color" or editor_property.get("t") == "color":
            error = max(abs(game_value[index] - editor_value[index]) for index in range(count))
            self.add("materials", "colorAbs", key, record, game_value, editor_value, error, self.tol["color"], near_cut=near, field=name)
            return
        score = 0.0
        error = 0.0
        for index in range(count):
            delta = abs(game_value[index] - editor_value[index])
            scale = max(abs(game_value[index]), abs(editor_value[index]))
            component = min(delta / self.tol["floatAbs"], delta / (self.tol["floatRel"] * scale) if scale > 0 else math.inf)
            if component > score:
                score, error = component, delta
        self.add("materials", "floatScore", key, record, game_value, editor_value, score, 1.0, near_cut=near, field=f"{name} (abs {error:.3g})")

    def cheek_toggle_note(self, game_material):
        """The AS/Member [Toggle] float _CHEEK is serialized but never written at runtime and is no uniform of the
        compiled shader (MemberCheekBase toggles only the _CHEEK_ON keyword): it is listed, not read as the
        keyword state, and the cheek floats are compared as the material holds them."""
        properties = game_material.get("properties") or {}
        if not self.identity and CHEEK_TOGGLE in properties and "_CheekIntensity" in properties:
            label = f"{game_material.get('name')}: {CHEEK_TOGGLE} {value_of(properties.get(CHEEK_TOGGLE))!r}"
            if label not in self.notes["materials.cheekToggleNotKeyword"]:
                self.notes["materials.cheekToggleNotKeyword"].append(label)

    def editor_material_properties(self, editor_material, game_material, editor_properties):
        """Unity properties of an editor material beyond its mapped `properties`, and the curve-driven ones removed.

        Editor-built shader materials (kind shader) carry their uniforms in `values`: _<Name> uniforms, the
        u<Name> lighting uniforms the LLAS C# components write with Material.Set* (SHADER_MATERIAL_PROPERTIES) and
        the aliases in SHADER_UNIFORM_ALIASES; uTextureST is the _MainTex scale/offset in the space the editor
        reports (textureSTSpace). Only properties the game material also has are compared. A uniform an
        AnimationTrack/Animator curve drives (curveDriven) is a MaterialPropertyBlock value in the game, which the
        game dump does not read (it reports the sharedMaterial base): it is listed as not comparable."""
        game_properties = game_material.get("properties") or {}
        curve = set(editor_material.get("curveDriven") or [])
        if editor_material.get("kind") == "shader":
            for uniform, held in (editor_material.get("values") or {}).items():
                if not isinstance(held, dict):
                    continue
                if uniform == "uTextureST":
                    space = editor_material.get("textureSTSpace")
                    if "_MainTex" in game_properties and space in ("unity", "gltf") and vector(held.get("v"), 4):
                        st = list(held["v"]) if space == "unity" else Conventions.texture_st(held["v"])
                        entry = editor_properties.setdefault("_MainTex", {"t": "tex", "v": None, "from": None})
                        entry.update(st=st, stFrom=uniform, stSpace=space)
                    continue
                unity = SHADER_UNIFORM_ALIASES.get(uniform) or (uniform if uniform.startswith("_") else None)
                if unity is None and Conventions.material_property(uniform) in SHADER_MATERIAL_PROPERTIES:
                    unity = Conventions.material_property(uniform)
                if unity is None or unity not in game_properties or held.get("t") == "tex":
                    continue
                kind = "color" if held.get("t") == "vector" and (game_properties[unity] or {}).get("t") == "color" else held.get("t")
                editor_properties.setdefault(unity, {"t": kind, "v": held.get("v"), "from": uniform})
        label = editor_material.get("editorName") or editor_material.get("name")
        for name in list(editor_properties):
            entry = editor_properties[name]
            if not isinstance(entry, dict) or not curve:
                continue
            if entry.get("from") in curve:
                self.notes["materials.notComparableMPB"].append(f"{label}:{name} ({entry['from']})")
                del editor_properties[name]
            elif entry.get("stFrom") in curve:
                # Only the scale/offset is curve-driven; the texture itself is still compared.
                self.notes["materials.notComparableMPB"].append(f"{label}:{name}_ST ({entry['stFrom']})")
                editor_properties[name] = {key: value for key, value in entry.items() if key not in ("st", "stFrom", "stSpace")}

    def compare_materials(self, record, partner, near):
        editor_materials = by_key(partner.get("materials"))
        for game_material in record.get("materials") or []:
            self.cheek_toggle_note(game_material)
            for use in game_material.get("usedBy") or []:
                renderer_key, _, slot = str(use).rpartition("#")
                editor_renderer = self.renderer_map.get(renderer_key)
                if editor_renderer is None:
                    self.notes["materials.unjoined"].append(use)
                    continue
                editor_material = editor_materials.get(f"material:{editor_renderer}#{slot}")
                if editor_material is None:
                    self.notes["materials.missingInEditor"].append(use)
                    continue
                editor_properties = {}
                for name, prop in (editor_material.get("properties") or {}).items():
                    unity = Conventions.material_property(name)
                    if unity:
                        editor_properties[unity] = prop
                values = editor_material.get("values") or {}
                key = f"material:{renderer_key}#{slot}"
                if editor_material.get("visible") is False:
                    label = f"{editor_material.get('editorName')} for {game_material.get('name')}"
                    hidden_uniforms = editor_material.get("hiddenUniforms")
                    if hidden_uniforms != "current":
                        # Stale uniforms (a penlight without clip input keeps the last clip's values), or a dump that does
                        # not say: only the claim that the draw adds nothing is checked against the game.
                        if label not in self.notes["materials.hiddenStale"]:
                            self.notes["materials.hiddenStale"].append(label)
                        if hidden_uniforms == "stale":
                            self.compare_hidden_draw(key, record, game_material, near)
                        continue
                    # Current uniforms (coloring hidden at tint alpha 0): compared like a drawn material.
                    if label not in self.notes["materials.hiddenCurrent"]:
                        self.notes["materials.hiddenCurrent"].append(label)
                if not self.identity:
                    self.editor_material_properties(editor_material, game_material, editor_properties)
                if not self.identity and editor_material.get("kind") == "gltf" and vector(values.get("color"), 3):
                    # A glTF slot multiplies its texture by color*opacity, as AS/* shaders do by _TintColor.
                    opacity = values.get("opacity") if number(values.get("opacity")) else 1.0
                    editor_properties.setdefault("_TintColor", {"t": "color", "v": list(values["color"]) + [opacity], "from": "gltf color/opacity"})
                    if isinstance(values.get("map"), dict):
                        editor_properties.setdefault("_MainTex", {"t": "tex", "v": values["map"], "from": "gltf map"})
                for name in editor_material.get("unmapped") or []:
                    if not (editor_material.get("kind") == "gltf" and name in ("color", "map")):
                        self.notes["materials.unmappedUniforms"].append(name)
                for name in editor_material.get("editorOnly") or []:
                    self.notes["materials.editorOnlyUniforms"].append(name)
                sampled = member_sampled_slots(editor_material)
                self.compare_member_variant(key, record, game_material, editor_material, near)
                for name, game_property in (game_material.get("properties") or {}).items():
                    editor_property = editor_properties.get(name)
                    if not isinstance(editor_property, dict):
                        self.notes["materials.notModeled"].append(f"{editor_material.get('kind')}:{name}")
                        continue
                    self.compare_property(key, name, record, game_property, editor_property, near, sampled=name in sampled)

    def compare_hidden_draw(self, key, record, game_material, near):
        """A hidden editor material draws nothing. The AS effect shaders the editor hides (coloring, penlight) multiply
        their output by _TintColor under SrcAlpha blending, so the game's draw adds nothing when its _TintColor alpha
        is 0; without that property the claim is not measurable."""
        tint = (game_material.get("properties") or {}).get("_TintColor")
        alpha = tint.get("v")[3] if isinstance(tint, dict) and vector(tint.get("v"), 4) else None
        if not number(alpha):
            self.notes["materials.hiddenNotMeasurable"].append(f"{key}: the game material has no _TintColor")
            return
        self.add("materials", "hiddenTintAlpha", key, record, alpha, 0.0, abs(alpha), self.tol["color"], near_cut=near,
                 field="_TintColor alpha (editor hides the material)")

    def compare_member_variant(self, key, record, game_material, editor_material, near):
        """AS/Member variant state: the keywords that select a compiled variant and the rim term."""
        if editor_material.get("kind") != "member":
            return
        game_keywords, editor_keywords = game_material.get("keywords"), editor_material.get("keywords")
        if isinstance(game_keywords, list) and isinstance(editor_keywords, list):
            game_variant = sorted(set(game_keywords) & MEMBER_VARIANT_KEYWORDS)
            editor_variant = sorted(set(editor_keywords) & MEMBER_VARIANT_KEYWORDS)
            self.add("materials", "variantKeywords", key, record, game_variant, editor_variant,
                     int(game_variant != editor_variant), 0, exact=True, near_cut=near, field="keywords")
            if sorted(set(game_keywords) - MEMBER_VARIANT_KEYWORDS) != sorted(set(editor_keywords) - MEMBER_VARIANT_KEYWORDS):
                self.notes["materials.otherKeywords"].append(f"game {sorted(game_keywords)}, editor {sorted(editor_keywords)}")
        # Every Hidden/AS/Member/Main variant adds the rim term: a lit rim the editor does not evaluate is missing.
        intensity = value_of((game_material.get("properties") or {}).get("_RimglightIntensity"))
        if editor_material.get("rimlightEvaluated") is False and number(intensity) and intensity > 0:
            self.add("materials", "rimlightEvaluated", key, record, intensity, False, 1, 0, exact=True, near_cut=near,
                     field="_RimglightIntensity")

    def compare_stage_nodes(self, record, partner, near):
        editor_nodes = by_key(partner.get("stageNodes"))
        for node in record.get("stageNodes") or []:
            if node.get("missing") is True:
                self.notes["stageNodes.gameMissing"].append(node.get("binding"))
                continue
            key = node.get("key") if self.identity else Conventions.stage_node_key(node.get("binding"), node.get("relPath"), node.get("crc"))
            self.coverage_sets["stageNodes"]["game"].add(key)
            editor_node = editor_nodes.get(key)
            if not editor_node:
                continue
            # The key's #crc is crc32 of the path below the binding; name that path so same-named nodes read apart.
            field = (node.get("relPath") or None) if not self.identity else editor_node.get("name")
            game_visible = node.get("visible") if self.identity else node.get("activeInHierarchy", node.get("visible"))
            if isinstance(game_visible, bool) and isinstance(editor_node.get("visible"), bool):
                self.add("visibility", "stageNodeVisible", key, record, game_visible, editor_node["visible"],
                         int(game_visible != editor_node["visible"]), 0, exact=True, near_cut=near)
            role = None
            if not self.identity:
                binding, rel = node.get("binding"), node.get("relPath")
                role = self.axis_billboard_role(f"{binding}/{rel}" if rel else binding)
                if role is None and editor_node.get("axisBillboard") is True:
                    role = "flagged"     # the editor's flag (a billboard or below one) without the serialized components
            if role and editor_node.get("axisBillboardDrawn") is True:
                # The editor reports the live camera's turn and that the live camera draws this billboard (its
                # AxisBillboard.Start bounds meet the frustum): the game's OnWillRenderObject turned it toward that
                # camera in the frame the record shows, so the whole transform is compared.
                if editor_node.get("name") not in self.notes["transforms.stageNodeAxisBillboardDrawn"]:
                    self.notes["transforms.stageNodeAxisBillboardDrawn"].append(editor_node.get("name"))
            elif role:
                # A stage node record has no draw state: the turn is the last target camera's draw (AXIS_BILLBOARD_CLASS).
                if editor_node.get("name") not in self.notes["transforms.stageNodeAxisBillboard"]:
                    self.notes["transforms.stageNodeAxisBillboard"].append(editor_node.get("name"))
                self.compare_billboard_transform("stageNode", key, record, node, editor_node, role, near, field)
                continue
            self.compare_transform("transforms", "stageNode", key, record, node, editor_node, self.tol["stagePositionM"], self.tol["stageRotationDeg"],
                                   near, field)

    def compare_members(self, record, partner, near):
        editor_members = {member.get("slot"): member for member in partner.get("members") or [] if isinstance(member, dict)}
        for member in record.get("members") or []:
            editor_member = editor_members.get(member.get("slot"))
            if not editor_member:
                continue
            editor_bones = by_key(editor_member.get("bones"))
            for bone in member.get("bones") or []:
                self.coverage_sets["bones"]["game"].add(bone.get("key"))
                editor_bone = editor_bones.get(bone.get("key"))
                if editor_bone:
                    self.compare_transform("transforms", "bone", bone["key"], record, bone, editor_bone,
                                           self.tol["bonePositionM"], self.tol["boneRotationDeg"], near)
            self.compare_blend_shapes(record, member, editor_member, near)

    def member_channels(self, entries, side):
        """Blend shape weights (0-100) of one member by channel name across its renderers. The game merges the
        face meshes into CombineFace (LiveCoreMemberHead); the editor keeps Face/Eye/Eye_Around/Mouth apart, so
        renderer keys never join: a channel name (EyeBlendShape.*, MouthBlendShape.*, *EyeWhiteLineBlendShape.*)
        is the same Unity blend shape on either side. Both sides list only non-zero weights."""
        channels, renderers = {}, 0
        for entry in entries or []:
            if not isinstance(entry, dict):
                continue
            weights = entry.get("weights") or {}
            if weights or (number(entry.get("count")) and entry["count"] > 0):
                renderers += 1
            for name, weight in weights.items():
                if not number(weight):
                    continue
                value = Conventions.blend_weight(weight, entry.get("unit"))
                if name in channels and abs(channels[name] - value) > self.tol["blendShapeWeight"]:
                    self.notes["blendShapes.rendererConflict"].append(f"{side} {name}: {channels[name]:.4g} vs {value:.4g}")
                channels[name] = max(channels.get(name, value), value)
        return channels, renderers

    def compare_blend_shapes(self, record, member, editor_member, near):
        game, game_renderers = self.member_channels(member.get("blendShapes") or member.get("morphs"), "game")
        editor, editor_renderers = self.member_channels(editor_member.get("morphs"), "editor")
        counts = self.blend_coverage
        counts["members"] += 1
        counts["gameRenderers"] += game_renderers
        counts["editorRenderers"] += editor_renderers
        counts["gameChannels"] += len(game)
        counts["editorChannels"] += len(editor)
        if not game_renderers or not editor_renderers:
            # No face renderer with blend shapes on one side: a 0 there is "not reported", not a weight.
            self.notes["blendShapes.noFaceRenderer"].append(f"slot {member.get('slot')}: game {game_renderers}, editor {editor_renderers}")
            return
        for name in sorted(set(game) | set(editor)):
            game_weight, editor_weight = game.get(name, 0.0), editor.get(name, 0.0)
            counts["samples"] += 1
            self.add("transforms", "blendShapeWeight", f"blendShape:member{member.get('slot')}:{name}", record, game_weight, editor_weight,
                     abs(game_weight - editor_weight), self.tol["blendShapeWeight"], near_cut=near)

    def spring_match(self, bone, editor_bones):
        """Editor key of a game swing bone: 'spring:<path>' -> member:<slot>:<path below the member's
        BodyPartManager root (members part rootPath)>; without a known root, the unique longest editor
        rig path of that slot that is a trailing part of the path below Member<N>."""
        if self.identity:
            return bone.get("key")
        path = bone.get("path")
        if not isinstance(path, str) and str(bone.get("key") or "").startswith("spring:"):
            path = bone["key"][len("spring:"):]
        key, fallback = Conventions.spring_bone_key(path, self.member_roots)
        if key or not fallback:
            return key
        slot, below = fallback
        prefix = f"member:{slot}:"
        candidates = sorted(((len(name) - len(prefix), name) for name in editor_bones
                             if name.startswith(prefix) and Conventions.path_suffix(below, name[len(prefix):])), reverse=True)
        if candidates and (len(candidates) == 1 or candidates[0][0] != candidates[1][0]):
            return candidates[0][1]
        return None

    def compare_springs(self, record, partner, near):
        editor_bones = {}
        managers = partner.get("springs") if isinstance(partner.get("springs"), list) else []
        for manager in managers:
            editor_bones.update(by_key(manager.get("bones")))
        for manager in record.get("springs") or []:
            for bone in manager.get("bones") or []:
                editor_key = self.spring_match(bone, editor_bones)
                editor_bone = editor_bones.get(editor_key) if editor_key else None
                if editor_bone is None:
                    self.notes["springs.unjoined"].append("no member root" if not self.member_roots else "no editor bone")
                    continue
                if vector(bone.get("localRotation"), 4) and vector(editor_bone.get("localRotation"), 4):
                    converted = self.quat(editor_bone["localRotation"])
                    self.add("springs", "springLocalRotationDeg", bone["key"], record, bone["localRotation"], converted,
                             qangle(bone["localRotation"], converted), self.tol["springRotationDeg"], near_cut=near, field=editor_key)

    def compare_post(self, record, partner, near):
        game_post, editor_post = record.get("post") or {}, partner.get("post") or {}
        if "enablePostEffect" in game_post and game_post["enablePostEffect"] is None:
            self.notes["post.gameUnresolved"].append(record.get("id"))
        if isinstance(game_post.get("enablePostEffect"), bool) and isinstance(editor_post.get("applied"), bool):
            self.add("post", "postEnabled", "post:enablePostEffect", record, game_post["enablePostEffect"], editor_post["applied"],
                     int(game_post["enablePostEffect"] != editor_post["applied"]), 0, exact=True, near_cut=near)
        for name in ("bloom", "dof", "flare"):
            if editor_post.get(name) is not None:
                self.notes["post.editorValues"].append(name)

    def compare_quality(self, record, partner, near):
        game_quality, editor_quality = record.get("quality") or {}, partner.get("quality") or {}
        editor_values = editor_quality.get("values") or {}
        for name, raw in (game_quality.get("values") or {}).items():
            key = name if self.identity else Conventions.quality_key(name)
            if key in Conventions.QUALITY_IGNORED:
                continue
            if key not in editor_values:
                self.notes["quality.gameOnly"].append(name)
                continue
            game_value = value_of(raw)
            self.add("quality", "qualityValue", f"quality:{key}", record, game_value, editor_values[key],
                     int(not Conventions.same_quality(game_value, editor_values[key])), 0, exact=True, near_cut=near, field=name)

    @staticmethod
    def particle_key(path):
        """'/<template> [Timeline]/<path>' (a ControlTrack instance at the scene root) -> '<template>/<path>',
        the editor's MVStudioParticleSystems.inspect() 'path'."""
        match = re.match(r"^/(.+?) \[Timeline\]/(.*)$", path or "")
        return f"{match.group(1)}/{match.group(2)}" if match else None

    def compare_particles(self, record, partner, near=False):
        particles = record.get("particles")
        if isinstance(particles, list):
            self.notes["particles.game"].append({"record": record.get("id"), "systems": len(particles),
                                                  "playing": sum(1 for item in particles if item.get("isPlaying")),
                                                  "particles": sum(item.get("particleCount") or 0 for item in particles)})
        if self.identity or not isinstance(particles, list) or not isinstance((partner or {}).get("particles"), list):
            return
        editor = {item.get("path"): item for item in partner["particles"] if isinstance(item, dict)}
        for item in particles:
            key = self.particle_key(item.get("path"))
            if key is None or not item.get("isPlaying"):
                continue          # SkillCutin and stopped systems; a game chunk lists only part of the systems
            match = editor.get(key)
            self.add("particles", "particleSystemPlaying", f"particles:{key}", record, True, match is not None,
                     int(match is None), 0, exact=True, near_cut=near)
            if match is None:
                continue
            game_count, editor_count = item.get("particleCount"), match.get("alive")
            if number(game_count) and number(editor_count):
                tol = max(self.tol["particleCountAbs"], self.tol["particleCountRel"] * max(game_count, editor_count))
                self.add("particles", "particleCount", f"particles:{key}", record, game_count, editor_count,
                         abs(game_count - editor_count), tol, near_cut=near,
                         field=f"seed game {item.get('randomSeed')} editor {match.get('seed')}")
            if number(item.get("randomSeed")) and number(match.get("seed")) and not item.get("useAutoRandomSeed"):
                self.add("particles", "particleSeed", f"particles:{key}", record, item["randomSeed"], match["seed"],
                         int(int(item["randomSeed"]) & 0xFFFFFFFF != int(match["seed"]) & 0xFFFFFFFF), 0, exact=True, near_cut=near)

    def census(self, records):
        for record in records:
            for node in (record.get("census") or {}).get("nodes") or []:
                kind, key = node.get("kind"), node.get("key")
                if kind == "stageNode":
                    self.coverage_sets["stageNodes"]["editor"].add(key)
                elif kind == "bone":
                    self.coverage_sets["bones"]["editor"].add(key)

    # -- FOV verdict
    def fov_verdict(self, frames, phase):
        tol = self.tol
        header, trailer = self.game.get("header") or {}, self.game.get("trailer") or {}
        bounds_sources = {}
        for where, block in (("header", header.get("fovmod")), ("trailer", trailer.get("fovmodEnd"))):
            if not isinstance(block, dict):
                continue
            for name in ("sfovrw22", "decoded"):
                values = block.get(name)
                if isinstance(values, dict) and number(values.get("min")) and number(values.get("max")):
                    bounds_sources[f"{where}.{name}"] = (values["min"], values["max"])
        bounds = next(iter(bounds_sources.values()), (0.75, 1.0))
        default_clamp = all(abs(low - 0.75) <= 1e-6 and abs(high - 1.0) <= 1e-6 for low, high in bounds_sources.values()) \
            if bounds_sources else None
        samples = []
        for record in frames:
            camera = main_camera(record)
            if not camera or not number(camera.get("fieldOfView")):
                continue
            correctors = by_key(record.get("correctors"))
            corrector = correctors.get("corrector:camera:main") or next(iter(correctors.values()), None)
            work = next(iter(record.get("cameraWork") or []), None) or {}
            fields = {name: value_of(raw) for name, raw in (work.get("fields") or {}).items() if number(value_of(raw))}
            if not fields and number(work.get("authoredFov")):
                fields = {"authoredFov": work["authoredFov"]}  # an editor document on the game side
            scene = record.get("scene") or {}
            screen = header.get("screen") or {}
            target = camera.get("targetTexture") or {}
            inputs = {"cameraAspect": camera.get("aspect"),
                      "screen": (scene.get("width") or screen.get("width") or 0) / (scene.get("height") or screen.get("height") or 1),
                      "renderTexture": (target.get("width") / target.get("height")) if number(target.get("width")) and number(target.get("height")) and target.get("height") else None,
                      "pixelRect": (camera["pixelWidth"] / camera["pixelHeight"]) if number(camera.get("pixelWidth")) and number(camera.get("pixelHeight")) and camera.get("pixelHeight") else None}
            partner = self.partner(record, phase)
            editor_camera = main_camera(partner) if partner else None
            editor_corrector = by_key((partner or {}).get("correctors")).get("corrector:camera:main")
            samples.append({"record": record.get("id"), "fov": camera["fieldOfView"], "correction": corrector.get("correction") if corrector else None,
                            "mode": value_of(corrector.get("mode")) if corrector else None, "fields": fields, "inputs": inputs,
                            "editorFov": editor_camera.get("fieldOfView") if editor_camera and editor_camera.get("liveShot", True) else None,
                            "editorAuthored": editor_camera.get("authoredFov") if editor_camera else None,
                            "editorCorrection": editor_corrector.get("correction") if editor_corrector else None})
        result = {"samples": len(samples), "bounds": {"value": list(bounds), "sources": {k: list(v) for k, v in bounds_sources.items()},
                                                       "default": default_clamp}}
        if not samples:
            result.update(verdict="RUNTIME_FOV_UNEXPLAINED", reason="no game frame record with a main camera FoV", editor="EDITOR_FOV_UNKNOWN")
            return result
        corrections = [sample["correction"] if number(sample["correction"]) else 1.0 for sample in samples]
        if not any(number(sample["correction"]) for sample in samples):
            result["note"] = "no CameraAspectCorrector recorded; Correction assumed 1"
        all_one = all(abs(value - 1) <= tol["correction"] for value in corrections)
        candidates = {}
        names = sorted({name for sample in samples for name in sample["fields"]})
        for name in names:
            linear = tan = total = 0
            for sample, correction in zip(samples, corrections):
                if name not in sample["fields"]:
                    continue
                total += 1
                authored = sample["fields"][name]
                if abs(authored / correction - sample["fov"]) <= tol["authoredMatchDeg"]:
                    linear += 1
                if 0 < authored < 180 and abs(math.degrees(2 * math.atan(math.tan(math.radians(authored) / 2) / correction)) - sample["fov"]) <= tol["authoredMatchDeg"]:
                    tan += 1
            if total:
                candidates[name] = {"linear": linear / total, "tan": tan / total, "samples": total}
        def pick(form):
            ranked = sorted((name for name, value in candidates.items() if value[form] >= tol["authoredFraction"]),
                            key=lambda name: (-candidates[name][form], "fov" not in name.lower(), name))
            return ranked[0] if ranked else None
        linear_field, tan_field = pick("linear"), pick("tan")
        authored_field = linear_field or tan_field
        result["cameraWorkCandidates"] = candidates
        result["authoredField"] = authored_field
        matching_inputs = []
        for name in ("cameraAspect", "screen", "renderTexture", "pixelRect"):
            values = [sample["inputs"].get(name) for sample in samples]
            if values and all(number(value) for value in values) and all(
                    abs(min(bounds[1], max(bounds[0], value / (16 / 9))) - correction) <= tol["correction"]
                    for value, correction in zip(values, corrections)):
                matching_inputs.append(name)
        result["correctionInput"] = matching_inputs
        result["correction"] = stats(corrections)
        if authored_field:
            ratios = [sample["fov"] / sample["fields"][authored_field] for sample in samples
                      if authored_field in sample["fields"] and sample["fields"][authored_field]]
            result["fovGameOverAuthored"] = stats(ratios)
        editor_ratios = [sample["editorFov"] / sample["fov"] for sample in samples if number(sample["editorFov"]) and sample["fov"]]
        result["fovEditorOverGame"] = stats(editor_ratios)
        correction_ratios = [c / sample["editorCorrection"] for sample, c in zip(samples, corrections)
                             if number(sample["editorCorrection"]) and sample["editorCorrection"]]
        result["correctionGameOverEditor"] = stats(correction_ratios)
        if all_one and authored_field and candidates[authored_field]["linear"] >= tol["authoredFraction"]:
            if default_clamp is False:
                verdict = "FOVMOD_NONDEFAULT_INACTIVE"
                reason = "the FOVMOD clamp is not [0.75, 1] but Correction is 1 everywhere, so the runtime FoV equals the authored FoV"
            else:
                verdict = "FOVMOD_DEFAULT_NO_CORRECTION"
                reason = ("Correction is 1 in every sample and the runtime FoV equals the authored CameraWork field "
                          f"{authored_field!r}: the FOVMOD setting and the stage FoV do not differ at this aspect")
        elif not all_one and linear_field:
            verdict, reason = "FOVMOD_CORRECTION_ACTIVE_LINEAR", f"runtime FoV = {linear_field} / Correction"
        elif not all_one and tan_field:
            verdict, reason = "FOVMOD_CORRECTION_ACTIVE_TAN", f"runtime FoV = 2 atan(tan({tan_field}/2) / Correction)"
        else:
            verdict = "RUNTIME_FOV_UNEXPLAINED"
            reason = "no CameraWork field reproduces the runtime FoV with the recorded Correction"
        result.update(verdict=verdict, reason=reason, discriminates=not all_one,
                      note16x9="At 16:9 Correction is 1, so a landscape run cannot tell the linear from the tan form."
                      if all_one else None)
        fov_items = [item for item in self.items if item["type"] == "camera" and item["metric"] == "fovAbsDeg" and not item["nearCut"]]
        worst = max((item["score"] for item in fov_items), default=None)
        result["editor"] = "EDITOR_FOV_UNKNOWN" if worst is None else ("EDITOR_FOV_MATCH" if worst <= 1 else "EDITOR_FOV_MISMATCH")
        result["editorFovError"] = stats([item["error"] for item in fov_items])
        return result

    # -- run
    def run(self):
        records = self.game["records"]
        frames = [record for record in records if record.get("kind") == "frame"]
        phase_info = self.calibrate(frames)
        phase = phase_info["chosen"]
        self.phase = phase
        globals_phase = self.calibrate_globals(frames)
        phase_info["globals"] = globals_phase
        cuts = self.cuts(phase)
        hypotheses = []
        joined, missing, time_errors = 0, [], []
        renderer_records = [record for record in records if record.get("part") == "renderers"]
        ordered = renderer_records + [record for record in records if record.get("part") != "renderers"]
        for record in ordered:
            partner = self.partner(record, phase)
            if partner is None:
                missing.append(record.get("id"))
                continue
            joined += 1
            source_time = (partner.get("clock") or {}).get("sourceDirectorTime", (partner.get("clock") or {}).get("directorTime"))
            game_time = (record.get("clock") or {}).get("directorTime")
            if number(source_time) and number(game_time):
                time_errors.append(abs(source_time - game_time))
            # A camera cut only moves camera-derived values (camera, aspect); other
            # asset types keep their own tolerances at any distance from a cut.
            if record.get("kind") == "frame":
                near = self.near_cut(record, phase, cuts)
                self.compare_camera(record, partner, near, hypotheses)
                self.compare_aspect(record, partner, near)
                self.compare_globals(record, self.partner(record, globals_phase) or partner, False)
                self.compare_member_identity(record, partner)
                continue
            # Full parts are not camera-derived: only a clamped deltaTime keeps them out of the ranking.
            part, uncertain = record.get("part"), self.timing_uncertain(record, phase)
            handler = {"renderers": self.compare_renderers, "materials": self.compare_materials, "stageNodes": self.compare_stage_nodes,
                       "members": self.compare_members, "springs": self.compare_springs, "post": self.compare_post,
                       "quality": self.compare_quality}.get(part)
            if handler:
                handler(record, partner, uncertain)
            elif part == "particles":
                self.compare_particles(record, partner, uncertain)
        # Camera hypothesis: the one with the lower median residual score (error / tolerance) over all frames.
        fitted, medians = None, {}
        if hypotheses:
            def w2c_score(errors):
                return max(error / tol if tol > 0 else (0.0 if error == 0 else EXACT_SCORE)
                           for error, tol in zip(errors, (self.tol["worldToCamera"], self.tol["cameraPositionM"])))

            for name in hypotheses[0][2]:
                medians[name] = statistics.median(w2c_score(errors[name]) for _, _, errors in hypotheses)
            fitted = min(medians, key=medians.get)
            for record, near, errors in hypotheses:
                basis, translation = errors[fitted]
                self.add("camera", "worldToCameraMaxAbs", "camera:main", record, None, None, basis, self.tol["worldToCamera"],
                         near_cut=near, field=fitted)
                self.add("camera", "worldToCameraTranslationM", "camera:main", record, None, None, translation,
                         self.tol["cameraPositionM"], near_cut=near, field=fitted)
            for record in frames:
                component = self.components.get(record.get("id"))
                if component:
                    game_rotation, expected = component
                    rotation = expected.get(fitted)
                    if rotation:
                        self.add("camera", "cameraComponentRotationDeg", "camera:main", record, game_rotation, rotation,
                                 qangle(game_rotation, rotation), self.tol["cameraRotationDeg"], near_cut=self.near_cut(record, phase, cuts), field=fitted)
        self.census([record for record in self.editor["records"]])
        game_globals = {key for record in frames for key, value in (record.get("globals") or {}).items() if value is not None}
        editor_globals = {key for record in self.editor["records"] for key, value in (record.get("globals") or {}).items() if value is not None}
        self.coverage_sets["globals"]["game"] |= game_globals
        self.coverage_sets["globals"]["editor"] |= editor_globals
        fov = self.fov_verdict(frames, phase)
        return self.report(phase_info, {"fitted": fitted, "medianResidual": medians}, joined, missing, time_errors, cuts, fov)

    @staticmethod
    def unavailable(records, field, nested=None):
        """Reasons the game dump gives for a value it could not read: record.unavailable[field], and with nested
        also record[nested][].unavailable[field] (a stripped class or an unregistered engine icall)."""
        reasons = Counter()
        for record in records:
            holders = [record] + [item for item in (record.get(nested) or []) if isinstance(item, dict)] if nested else [record]
            for holder in holders:
                reason = (holder.get("unavailable") or {}).get(field) if isinstance(holder.get("unavailable"), dict) else None
                if isinstance(reason, str) and reason:
                    reasons[reason] += 1
        return reasons

    def negative_controls(self, frames):
        """Game-only negative controls. A value the game dump reports unavailable (and never read) is not measurable:
        the reason is reported instead of an empty list or a null that would read as 'nothing there'."""
        def not_measurable(reasons):
            return "not measurable: " + reasons.most_common(1)[0][0]

        unavailable = {}
        settings = next((record.get("renderSettings") for record in frames if isinstance(record.get("renderSettings"), dict)
                         and "modeled" not in record.get("renderSettings")), None)
        reasons = self.unavailable(frames, "renderSettings")
        if reasons:
            unavailable["renderSettings"] = {"reason": reasons.most_common(1)[0][0], "records": sum(reasons.values())}
            if settings is None:
                settings = not_measurable(reasons)
        lights = [light for record in frames for light in (record.get("lights") or []) if isinstance(light, dict)]
        lights_read = any(isinstance(record.get("lights"), list) for record in frames)
        reasons = self.unavailable(frames, "lights")
        light_count = len({light.get("key") for light in lights})
        with_intensity = sorted({light.get("key") for light in lights if number(light.get("intensity")) and light["intensity"] > 0})
        if reasons:
            unavailable["lights"] = {"reason": reasons.most_common(1)[0][0], "records": sum(reasons.values())}
            if not lights_read:
                light_count = with_intensity = not_measurable(reasons)
        renderer_records = [record for record in self.game["records"] if record.get("part") == "renderers"]
        renderers = [item for record in renderer_records for item in (record.get("renderers") or []) if isinstance(item, dict)]
        blocks = [item for item in renderers if isinstance(item.get("hasPropertyBlock"), bool)]
        reasons = self.unavailable(renderer_records, "hasPropertyBlock", nested="renderers")
        property_blocks = ({"renderers": len({item.get("key") for item in blocks}),
                            "withPropertyBlock": sorted({item.get("key") for item in blocks if item["hasPropertyBlock"]})[:40]}
                           if blocks else None)
        if reasons:
            unavailable["hasPropertyBlock"] = {"reason": reasons.most_common(1)[0][0], "records": sum(reasons.values())}
            if property_blocks is None:
                property_blocks = not_measurable(reasons)
        return {"renderSettings": settings, "lights": light_count, "lightsWithIntensity": with_intensity,
                "propertyBlocks": property_blocks, "unavailable": unavailable,
                "info": "game-only negative controls: no SIFAS shader reads RenderSettings or Unity lights"}

    def timing(self):
        frames = [record for record in self.game["records"] if record.get("kind") == "frame"]
        single = [record for record in frames if number((record.get("clock") or {}).get("frameCount"))
                  and (record.get("clock") or {}).get("frameCount") == (record.get("clockEnd") or {}).get("frameCount")]
        with_counts = [record for record in frames if number((record.get("clock") or {}).get("frameCount"))]
        # clock.musicTime is LiveMusicMachine milliseconds (1601 at directorTime 1.601).
        music = [record["clock"]["directorTime"] - record["clock"]["musicTime"] / 1000.0 for record in frames
                 if number((record.get("clock") or {}).get("musicTime")) and number(record["clock"].get("directorTime"))]
        return {"frames": len(frames), "singleFrameFraction": (len(single) / len(with_counts)) if with_counts else None,
                "directorMinusMusic": stats(music)}

    def coverage(self):
        expected = expected_keys(self.keys)
        result = {}
        for name, sets in self.coverage_sets.items():
            game, editor = sets["game"], sets["editor"]
            entry = {"game": len(game), "editor": len(editor),
                     "missingInEditor": sorted(map(str, game - editor))[:50] if editor else [],
                     "missingInEditorCount": len(game - editor) if editor else None,
                     "extraInEditor": sorted(map(str, editor - game))[:50] if game else [],
                     "extraInEditorCount": len(editor - game) if game else None}
            if expected and name in expected:
                both = expected[name] - game - editor
                entry["expected"] = len(expected[name])
                entry["missingFromBoth"] = sorted(map(str, both))[:50]
                entry["missingFromBothCount"] = len(both)
            result[name] = entry
        result["renderers"] = self.renderer_coverage(expected)
        result["ambiguousRenderers"] = sorted(self.ambiguous)[:50]
        result["ambiguousRenderersCount"] = len(self.ambiguous)
        return result

    def renderer_coverage(self, expected):
        """Renderer coverage on the join key (scope, GameObject path below the scope root)."""
        def label(key):
            scope, relative = self.game_renderers.get(key, (None, None))
            return f"{scope}:{relative}" if relative is not None else key
        joined = {editor for editor, _ in self.joins.values() if editor}
        missing = sorted(label(key) for key, (editor, method) in self.joins.items() if editor is None and method not in ("ambiguous", "gameNullMesh"))
        extra = sorted(set(self.editor_catalog) - joined - self.ambiguous_candidates) if self.joins else []
        entry = {"game": len(self.joins), "editor": len(self.editor_catalog), "joined": len(joined), "joinedBy": dict(self.join_methods),
                 "editorFlattened": sum(1 for item in self.editor_catalog.values() if item["path"] is None),
                 "missingInEditor": missing[:50] if self.editor_catalog else [],
                 "missingInEditorCount": len(missing) if self.editor_catalog else None,
                 "extraInEditor": extra[:50], "extraInEditorCount": len(extra) if self.joins else None}
        if expected and "renderers" in expected:
            present = defaultdict(set)
            for scope, relative in self.game_renderers.values():
                if relative is not None:
                    present[scope].add(relative)
            for item in self.editor_catalog.values():
                if item["relative"] is not None:
                    present[item["scope"]].add(item["relative"])
            both = sorted(f"{scope}:{relative}" for scope, relative in expected["renderers"]
                          if not any(found == relative or Conventions.path_suffix(found, relative) for found in present.get(scope, ())))
            entry.update(expected=len(expected["renderers"]), missingFromBoth=both[:50], missingFromBothCount=len(both))
        return entry

    def part_coverage(self):
        """Per game part (frame records under "frame"): how many records, how many joined an editor record at the
        chosen phase, the director times they span and the samples they produced, so a part the game sampled only
        early in the song (a preempted pass) or one that produced no sample is visible. Passes come from the game
        trailer (parts sampled per pass, its window and whether it completed)."""
        trailer = self.game.get("trailer") or {}
        end = (trailer.get("coverage") or {}).get("directorLast")
        frames = [(record.get("clock") or {}).get("directorTime") for record in self.game["records"] if record.get("kind") == "frame"]
        if not number(end):
            end = max((t for t in frames if number(t)), default=None)
        samples = Counter(item["record"] for item in self.items)
        parts = {}
        for record in self.game["records"]:
            part = "frame" if record.get("kind") == "frame" else record.get("part") or record.get("kind") or "other"
            entry = parts.setdefault(part, {"records": 0, "joined": 0, "samples": 0, "tFirst": None, "tLast": None})
            entry["records"] += 1
            entry["joined"] += int(self.partner(record, getattr(self, "phase", 0)) is not None)
            entry["samples"] += samples.get(record.get("id"), 0)
            t = (record.get("clock") or {}).get("directorTime")
            if number(t):
                entry["tFirst"] = t if entry["tFirst"] is None else min(entry["tFirst"], t)
                entry["tLast"] = t if entry["tLast"] is None else max(entry["tLast"], t)
        for entry in parts.values():
            entry["uncoveredTail"] = (end - entry["tLast"]) if number(end) and number(entry["tLast"]) else None
        passes = [{name: item.get(name) for name in ("pass", "parts", "startedAt", "endedAt", "complete", "closed")}
                  for item in trailer.get("passes") or [] if isinstance(item, dict)]
        return {"songEnd": end, "parts": dict(sorted(parts.items())), "passes": passes,
                "blendShapes": dict(self.blend_coverage)}

    def quality_validity(self):
        """Contract 5: the editor must have run at the game's quality (header.quality.values)."""
        if self.identity:
            return {"status": "valid", "reasons": [], "quality": {"mode": "identity"}}
        game_quality = (self.game.get("header") or {}).get("quality") or {}
        editor_quality = (self.editor.get("header") or {}).get("quality") or {}
        values = game_quality.get("values") if isinstance(game_quality.get("values"), dict) else {}
        editor_values = editor_quality.get("values") if isinstance(editor_quality.get("values"), dict) else {}
        reasons, differences, game_only, compared = [], [], [], 0
        if not values:
            reasons.append("the game dump records no quality values (header.quality.values)")
        for name, raw in values.items():
            key = Conventions.quality_key(name)
            if key in Conventions.QUALITY_IGNORED:
                continue
            if key not in editor_values:
                game_only.append(name)
                continue
            compared += 1
            if not Conventions.same_quality(value_of(raw), editor_values[key]):
                differences.append({"game": name, "editor": key, "gameValue": value_of(raw), "editorValue": editor_values[key]})
        if differences:
            reasons.append(f"{len(differences)} game quality value(s) differ from the quality the editor ran: "
                           + ", ".join(f"{item['game']}={item['gameValue']!r}/{item['editorValue']!r}" for item in differences[:8]))
        status = editor_quality.get("status")
        if status not in (None, "matched"):
            reasons += [f"editor capture: {reason}" for reason in editor_quality.get("reasons") or [status]]
        performers = [f"slot {slot}: game member {value['game']['memberId']} suit {value['game']['suitId']}, editor member "
                      f"{value['editor']['memberId']} costume {value['editor']['costumeId']}" for slot, value in sorted(self.performer_mismatch.items())]
        return {"status": "invalid:quality" if reasons else ("partial:performer" if performers else "valid"), "reasons": reasons,
                "performers": performers,
                "quality": {"compared": compared, "differences": differences, "gameOnly": game_only,
                            "editorSource": editor_quality.get("source"), "editorMode": editor_quality.get("mode"),
                            "editorStatus": status}}

    def groups(self):
        """One group per (type, key, metric) over the samples outside camera cuts: the worst sample,
        the sample and beyond-tolerance counts and the first and last director time."""
        groups = {}
        for item in self.items:
            if item["nearCut"]:
                continue
            ident = (item["type"], item["key"], item["metric"])
            group = groups.get(ident)
            if group is None:
                group = groups[ident] = {"type": item["type"], "metric": item["metric"], "key": item["key"], "count": 0, "beyond": 0,
                                         "tFirst": None, "tLast": None, "records": [], "_worst": item}
            group["count"] += 1
            t = item["t"]
            if number(t):
                group["tFirst"] = t if group["tFirst"] is None else min(group["tFirst"], t)
                group["tLast"] = t if group["tLast"] is None else max(group["tLast"], t)
            if item["score"] > 1:
                group["beyond"] += 1
                if len(group["records"]) < 10 and item["record"] not in group["records"]:
                    group["records"].append(item["record"])
            if item["score"] > group["_worst"]["score"]:
                group["_worst"] = item
        result = []
        for group in groups.values():
            worst = group.pop("_worst")
            performer = bool(self.performer_mismatch) and group["type"] in ("visibility", "transforms", "materials") and \
                group["metric"].startswith(("renderer", "slotName", "float", "color", "texture")) and "/Live/Members/Member" in str(group["key"])
            result.append(dict(group, field=worst["field"], t=worst["t"], record=worst["record"], game=worst["game"],
                               editorConverted=worst["editorConverted"], error=worst["error"], tol=worst["tol"], score=worst["score"],
                               diagnostic=group["type"] in DIAGNOSTIC_TYPES or performer,
                               **({"diagnosticReason": "the editor dressed the member in a different suit"} if performer else {})))
        result.sort(key=lambda group: (-group["score"], group["type"], str(group["key"]), group["metric"]))
        return result

    @staticmethod
    def compact(group):
        return {name: group[name] for name in ("type", "metric", "key", "score", "count", "beyond", "tFirst", "tLast")}

    def report(self, phase_info, hypothesis, joined, missing, time_errors, cuts, fov):
        groups = self.groups()
        ranked = [group for group in groups if not group["diagnostic"]]
        beyond = [group for group in ranked if group["score"] > 1]
        types = {}
        for type_ in TYPES:
            items = [item for item in self.items if item["type"] == type_]
            metrics, scores = defaultdict(list), defaultdict(float)
            for item in items:
                if not item["nearCut"]:
                    metrics[item["metric"]].append(item["error"] if isinstance(item["error"], (int, float)) else None)
                    scores[item["metric"]] = max(scores[item["metric"]], item["score"])
            type_groups = [group for group in groups if group["type"] == type_]
            types[type_] = {"n": len(items), "nearCut": sum(1 for item in items if item["nearCut"]), "groups": len(type_groups),
                            "beyondTolerance": sum(1 for group in type_groups if group["score"] > 1),
                            "beyondSamples": sum(group["beyond"] for group in type_groups),
                            "diagnostic": type_ in DIAGNOSTIC_TYPES,
                            "metrics": {name: dict(stats(values) or {"n": 0}, maxScore=scores[name])
                                        for name, values in sorted(metrics.items(), key=lambda pair: (-scores[pair[0]], pair[0]))},
                            "worst": [self.compact(group) for group in type_groups[:5]]}
        notes = {}
        for name, values in self.notes.items():
            if name == "visibility.isVisible":
                notes[name] = {"true": sum(values), "false": len(values) - sum(values)}
            elif values and isinstance(values[0], str):
                counts = Counter(values)
                notes[name] = {"count": len(values), "unique": [{"value": key, "n": n} for key, n in counts.most_common(40)]}
            else:
                notes[name] = values[:40]
        game_header = self.game.get("header") or {}
        frames = [record for record in self.game["records"] if record.get("kind") == "frame"]
        negative = self.negative_controls(frames)
        per_type_top = {type_: [group for group in ranked if group["type"] == type_][:5] for type_ in TYPES}
        validity = self.quality_validity()
        report = {
            "schema": REPORT_SCHEMA, "createdAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "validity": validity,
            "inputs": {side: {"file": doc.get("_source", {}).get("file"), "sha256": doc.get("_source", {}).get("sha256"), "side": doc.get("side"),
                              "records": len(doc["records"]), "producer": ((doc.get("header") or {}).get("producer") or {}).get("name"),
                              "budgets": (doc.get("header") or {}).get("budgets"),
                              "auxiliaryBlobs": doc.get("_source", {}).get("auxiliaryBlobs", [])}
                       for side, doc in (("game", self.game), ("editor", self.editor))},
            "tolerances": self.tol,
            "join": {"mode": "identity" if self.identity else "game-vs-editor", "phase": phase_info, "hypothesis": hypothesis,
                     "joinedRecords": joined, "missingEditorRecords": missing[:50], "missingEditorRecordsCount": len(missing),
                     "timeJoinMaxError": max(time_errors) if time_errors else None, "cuts": len(cuts),
                     "nearCutItems": sum(1 for item in self.items if item["nearCut"]),
                     "renderers": dict(self.join_methods), "memberRoots": {str(slot): root for slot, root in sorted(self.member_roots.items())}},
            "timing": self.timing(),
            "fov": fov,
            "negativeControls": negative,
            "types": types,
            "coverage": self.coverage(),
            "notes": notes,
            "ranked": {"overall": ranked[:25], "perType": per_type_top},
            "groups": {"count": len(groups), "ranked": len(ranked), "beyond": [self.compact(group) for group in beyond]},
            "summary": {"items": len(self.items), "ranked": len(ranked),
                        "rankedSamples": sum(group["count"] for group in ranked), "beyondTolerance": len(beyond),
                        "beyondSamples": sum(group["beyond"] for group in ranked),
                        "worstScore": ranked[0]["score"] if ranked else 0.0, "verdict": fov.get("verdict"), "editorFov": fov.get("editor"),
                        "beyondByType": {type_: types[type_]["beyondTolerance"] for type_ in TYPES
                                         if types[type_]["beyondTolerance"] and not types[type_]["diagnostic"]},
                        "gameQuality": (game_header.get("quality") or {}).get("values"), "validity": validity["status"]},
        }
        report["_worst"] = beyond if beyond else ranked[:100]
        report["partCoverage"] = self.part_coverage()
        return report


# ------------------------------------------------------------------ output

def _fmt(value):
    if isinstance(value, float):
        return f"{value:.6g}"
    if isinstance(value, list):
        return "[" + ", ".join(_fmt(item) for item in value[:6]) + (", …" if len(value) > 6 else "") + "]"
    if isinstance(value, dict):
        return json.dumps(value, separators=(",", ":"))[:80]
    return str(value)


def write_markdown(report, path):
    lines = ["# MV runtime value comparison", "",
             f"Game: `{report['inputs']['game']['file']}` ({report['inputs']['game']['records']} records, side {report['inputs']['game']['side']})  ",
             f"Editor: `{report['inputs']['editor']['file']}` ({report['inputs']['editor']['records']} records)", ""]
    validity = report["validity"]
    if validity["status"].startswith("invalid"):
        lines += [f"> **{validity['status'].upper()}**: the editor did not run at the game's quality, so quality-gated asset types "
                  "(post, visibility of quality-gated nodes, springs, render resolution) are not comparable. "
                  + "; ".join(validity["reasons"]), ""]
    if validity.get("performers"):
        lines += ["> **PARTIAL:PERFORMER**: the editor dressed a member differently from the game, so that member's renderer, "
                  "material and renderer-transform groups are diagnostic (bones and anchors are still ranked): "
                  + "; ".join(validity["performers"]), ""]
    join = report["join"]
    lines += [f"Join: {join['mode']}, phase {join['phase'].get('chosen')} ({join['phase'].get('method')}), histogram "
              f"{join['phase'].get('histogram')}, camera hypothesis {join['hypothesis'].get('fitted')} "
              f"(median W2C residual score {join['hypothesis'].get('medianResidual')}), {join['joinedRecords']} records joined, "
              f"{join['missingEditorRecordsCount']} without an editor record, time join max error {join['timeJoinMaxError']}, "
              f"renderer joins {join['renderers'] or 'none'}.", ""]
    summary = report["summary"]
    lines += ["## Summary", "", f"**{summary['beyondTolerance']} distinct discrepancies beyond tolerance** "
              f"({summary['beyondSamples']} samples) out of {summary['ranked']} ranked (type, key, metric) groups "
              f"(worst score {summary['worstScore']:.4g}). By type: {summary['beyondByType'] or 'none'}. Validity: {summary['validity']}.", ""]
    fov = report["fov"]
    lines += ["## FOV verdict", "", f"**{fov.get('verdict')}** / **{fov.get('editor')}**: {fov.get('reason')}.", "",
              "The FOVMOD \"FOV setting\" is not an angle: it is the [min, max] clamp on CameraAspectCorrector.Correction "
              f"(recorded bounds {fov.get('bounds')}). Authored CameraWork field: `{fov.get('authoredField')}`; Correction input(s) "
              f"reproducing the recorded Correction: {fov.get('correctionInput')}; Correction {_fmt(fov.get('correction'))}; "
              f"fov game/authored {_fmt(fov.get('fovGameOverAuthored'))}; fov editor/game {_fmt(fov.get('fovEditorOverGame'))}; "
              f"Correction game/editor {_fmt(fov.get('correctionGameOverEditor'))}.", ""]
    if fov.get("note16x9"):
        lines += [fov["note16x9"], ""]
    lines += ["## Per asset type", "", "| type | samples | groups | beyond (groups) | beyond (samples) | near cut | worst keys |",
              "|---|---:|---:|---:|---:|---:|---|"]
    for type_, entry in report["types"].items():
        if not entry["n"]:
            continue
        worst = "; ".join(f"{item['key']} ({item['metric']} {item['score']:.3g}, ×{item['count']})" for item in entry["worst"][:3])
        lines.append(f"| {type_}{' (diagnostic)' if entry['diagnostic'] else ''} | {entry['n']} | {entry['groups']} | {entry['beyondTolerance']} | "
                     f"{entry['beyondSamples']} | {entry['nearCut']} | {worst} |")
    lines += ["", "### Metrics (error statistics over samples; max score = max error / tolerance)", "",
              "| type | metric | n | p50 | p95 | max | max score |", "|---|---|---:|---:|---:|---:|---:|"]
    for type_, entry in report["types"].items():
        for metric, value in entry["metrics"].items():
            if value.get("n"):
                lines.append(f"| {type_} | {metric} | {value['n']} | {value['p50']:.3g} | {value['p95']:.3g} | {value['max']:.3g} | "
                             f"{value['maxScore']:.3g} |")
    lines += ["", "## Ranked (top 25 distinct (type, key, metric) groups, score = worst error / tolerance)", "",
              "| # | type | metric | key | field | worst t | t range | samples (beyond) | game | editor (converted) | score |",
              "|---:|---|---|---|---|---:|---|---:|---|---|---:|"]
    for rank, item in enumerate(report["ranked"]["overall"], 1):
        lines.append(f"| {rank} | {item['type']} | {item['metric']} | `{item['key']}` | {item['field'] or ''} | {_fmt(item['t'])} | "
                     f"{_fmt(item['tFirst'])}–{_fmt(item['tLast'])} | {item['count']} ({item['beyond']}) | "
                     f"{_fmt(item['game'])} | {_fmt(item['editorConverted'])} | {item['score']:.4g} |")
    coverage = report["coverage"]
    lines += ["", "## Coverage", ""]
    for name, entry in coverage.items():
        if isinstance(entry, dict):
            lines.append(f"- {name}: game {entry['game']}, editor {entry['editor']}, missing in editor {entry.get('missingInEditorCount')}, "
                         f"extra in editor {entry.get('extraInEditorCount')}" +
                         (f", joined by {entry['joinedBy']}, editor renderers without a GameObject path {entry['editorFlattened']}"
                          if "joinedBy" in entry else "") +
                         (f", expected {entry['expected']}, missing from both {entry['missingFromBothCount']}" if "expected" in entry else ""))
    lines += [f"- ambiguous renderer joins: {coverage['ambiguousRenderersCount']}", ""]
    parts = report.get("partCoverage") or {}
    if parts.get("parts"):
        blend = parts.get("blendShapes") or {}
        lines += ["### Coverage per game part", "", f"Song end {_fmt(parts.get('songEnd'))} s. A part whose last record is far "
                  "before the end has no game sample there: later shots are pixel-only for it.", "",
                  "| part | records | joined | samples | first t | last t | uncovered tail (s) |", "|---|---:|---:|---:|---:|---:|---:|"]
        for name, entry in parts["parts"].items():
            lines.append(f"| {name} | {entry['records']} | {entry['joined']} | {entry['samples']} | {_fmt(entry['tFirst'])} | "
                         f"{_fmt(entry['tLast'])} | {_fmt(entry['uncoveredTail'])} |")
        for item in parts.get("passes") or []:
            lines.append(f"- pass {item.get('pass')}: {_fmt(item.get('startedAt'))}-{_fmt(item.get('endedAt'))} s, parts "
                         f"{', '.join(item.get('parts') or [])}{'' if item.get('complete') else ' (incomplete' + (': ' + item['closed'] if item.get('closed') else '') + ')'}")
        lines += ["", f"Blend shapes (per member slot, joined by channel name): {blend.get('samples', 0)} samples from "
                  f"{blend.get('members', 0)} member records; non-zero channels game {blend.get('gameChannels', 0)}, editor "
                  f"{blend.get('editorChannels', 0)}; face renderers game {blend.get('gameRenderers', 0)}, editor "
                  f"{blend.get('editorRenderers', 0)}.", ""]
    lines += [
              "## Negative controls", "", f"{report['negativeControls']['info']}; lights {report['negativeControls']['lights']}, "
              f"with intensity > 0: {report['negativeControls']['lightsWithIntensity']}.", "",
              f"- RenderSettings: {_negative(report['negativeControls'].get('renderSettings'))}",
              f"- MaterialPropertyBlocks (Renderer.HasPropertyBlock): {_negative(report['negativeControls'].get('propertyBlocks'))}", "",
              "## Timing", "", f"{report['timing']}", ""]
    Path(path).write_text("\n".join(lines) + "\n", "utf-8")


def _negative(value):
    if value is None:
        return "not in the game dump"
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True)[:400]


def write_csv(groups, path):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["type", "metric", "key", "field", "score", "count", "beyond", "tFirst", "tLast", "t", "record", "error", "tol",
                         "game", "editorConverted"])
        for group in groups:
            writer.writerow([group["type"], group["metric"], group["key"], group["field"] or "", group["score"], group["count"], group["beyond"],
                             group["tFirst"], group["tLast"], group["t"], group["record"], group["error"], group["tol"],
                             json.dumps(group["game"]), json.dumps(group["editorConverted"])])


def regressions(report, baseline):
    """New (type, key, metric) groups beyond tolerance, and groups whose worst score at least
    doubled. Sample counts never regress: a longer run of the same defect is the same defect."""
    beyond = (baseline.get("groups") or {}).get("beyond") if isinstance(baseline.get("groups"), dict) else None
    if baseline.get("schema") != REPORT_SCHEMA or not isinstance(beyond, list):
        return [f"baseline schema {baseline.get('schema')!r} has no deduplicated groups; regenerate it with this comparator ({REPORT_SCHEMA})"]
    before = {(group["type"], group["key"], group["metric"]): group for group in beyond}
    found = []
    for group in report["groups"]["beyond"]:
        old = before.get((group["type"], group["key"], group["metric"]))
        if old is None:
            found.append(f"new {group['type']} discrepancy {group['key']} {group['metric']} (score {group['score']:.4g}, "
                         f"{group['beyond']} samples, t {group['tFirst']}..{group['tLast']})")
        elif group["score"] >= WORSENED_FACTOR * old["score"]:
            found.append(f"worse {group['type']} {group['key']} {group['metric']}: score {old['score']:.4g} -> {group['score']:.4g}")
    return found


def compare_files(game_path, editor_path, out, keys_path=None, tolerances_path=None, phase="auto", baseline=None):
    game, editor = load_dump(game_path), load_dump(editor_path)
    keys = json.loads(Path(keys_path).read_text("utf-8")) if keys_path else None
    tolerances = json.loads(Path(tolerances_path).read_text("utf-8")) if tolerances_path else None
    report = Comparison(game, editor, tolerances, phase, keys).run()
    worst = report.pop("_worst")
    if baseline:
        previous = json.loads(Path(baseline).read_text("utf-8"))
        report["baseline"] = {"path": str(Path(baseline).resolve()), "regressions": regressions(report, previous),
                              "validity": {"baseline": (previous.get("validity") or {}).get("status"), "current": report["validity"]["status"]}}
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, indent=1, default=str) + "\n", "utf-8")
    write_markdown(report, out / "report.md")
    write_csv(worst, out / "worst.csv")
    return report


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--game", required=True, help="game dump (.json, .json.gz or job log); an editor dump gives an identity join")
    parser.add_argument("--editor", required=True, help="editor dump from tests/mv_runtime_capture.js")
    parser.add_argument("--out", required=True, help="report directory")
    parser.add_argument("--keys", help="expected per-song keys (12035-runtime-keys.json)")
    parser.add_argument("--tolerances", help="JSON object overriding DEFAULT_TOLERANCES")
    parser.add_argument("--phase", default="auto", choices=["auto", "-1", "0", "1"])
    parser.add_argument("--baseline", help="earlier report.json to diff against")
    parser.add_argument("--fail-on-regression", action="store_true")
    parser.add_argument("--require-valid", action="store_true", help="exit 3 when the report is invalid (e.g. invalid:quality)")
    return parser.parse_args(argv)


def main(argv=None):
    arguments = parse_args(argv)
    report = compare_files(arguments.game, arguments.editor, arguments.out, arguments.keys, arguments.tolerances,
                           arguments.phase, arguments.baseline)
    summary = report["summary"]
    print(json.dumps({"out": str(Path(arguments.out).resolve()), "validity": report["validity"]["status"],
                      "beyondTolerance": summary["beyondTolerance"], "beyondSamples": summary["beyondSamples"],
                      "ranked": summary["ranked"], "worstScore": summary["worstScore"], "phase": report["join"]["phase"]["chosen"],
                      "hypothesis": report["join"]["hypothesis"]["fitted"], "fov": summary["verdict"], "editorFov": summary["editorFov"],
                      "beyondByType": summary["beyondByType"], "rendererJoins": report["join"]["renderers"]}))
    if arguments.fail_on_regression and report.get("baseline", {}).get("regressions"):
        return 2
    if arguments.require_valid and report["validity"]["status"] != "valid":
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
