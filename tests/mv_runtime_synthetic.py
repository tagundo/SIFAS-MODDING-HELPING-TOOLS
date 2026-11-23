"""Synthetic game-side runtime dumps for testing the editor capture and the comparator.

    python tests/mv_runtime_synthetic.py skeleton --times 14.85,35.2167,... [--full-at 14.85,50.3333]
        [--parts renderers,materials,...] [--delta 0.0666667] --out GAME.json.gz
    python tests/mv_runtime_synthetic.py mirror --editor EDITOR.json.gz --out GAME.json.gz [--hypothesis H180|H0] [--source-phase 0]
    python tests/mv_runtime_synthetic.py perturb --game GAME.json.gz --out PERTURBED.json.gz [--fov 2] [--camera-move 0.1]
        [--material-delta 0.05] [--hide true] [--manifest perturbations.json]
    python tests/mv_runtime_synthetic.py joblog --game GAME.json.gz --out job.log

"skeleton" writes a game-style document (side "game") that carries only the
record envelope and clock (plus header.quality.values {"Quality": mode} from
--manifest): it is a list of director times for tests/mv_runtime_capture.js,
not game values. "mirror" turns an editor dump into the game document the real
game would have produced if it agreed with the editor exactly, using only the
inverses in mv_runtime_compare.Conventions: game-style renderer keys and
GameObject paths ("renderer:<path>"), layers and a main camera culling mask
that excludes the synthetic Invisible layer, Unity texture ST, member root
paths and "spring:<path>" swing-bone keys. "perturb" injects known
discrepancies into such a document. "joblog" emits the @@RTDUMP job-log
transport of schema section 8, including the rtdump-probe blob.
"""
import argparse
import base64
import copy
import gzip
import hashlib
import json
import math
from pathlib import Path
import sys
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mv_runtime_compare import SCHEMA, Conventions, load_dump  # noqa: E402

GAME_CONVENTIONS = {"space": "unity-lh", "matrixLayout": "column-major", "angles": "degrees", "quaternion": "xyzw",
                    "color": "raw", "time": "director-seconds"}
DEFAULT_PARTS = ("census", "quality", "renderers", "materials", "members", "springs", "stageNodes", "particles", "post")
# Synthetic stand-ins for values only a real game run knows: the GameObject layer a
# LiveMemberCullerClip moves a member to, and where the flattened stage model and the
# member prefab sit in the game hierarchy.
INVISIBLE_LAYER = 30
MAIN_CULLING_MASK = -1 ^ (1 << INVISIBLE_LAYER)
STAGE_ROOT = "/EntryPoint/Live/Stages/MainStage"
EFFECT_ROOT = STAGE_ROOT + "/Effect"
MEMBER_MODEL = "Model/synthetic_member"


def write_dump(doc, path):
    data = json.dumps({key: value for key, value in doc.items() if not key.startswith("_")}, separators=(",", ":")).encode("utf-8")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(data, 9, mtime=0) if path.suffix == ".gz" else data)
    return path


def game_header(source, screen, quality_values=None, producer="mv_runtime_synthetic.py", extra=None):
    width, height = screen
    header = {
        "createdAt": "2026-11-23T00:00:00Z",
        "producer": {"name": producer, "synthetic": True, "samplerVersion": 1},
        "conventions": dict(GAME_CONVENTIONS),
        "source": {"region": source.get("region", "gl"), "platform": source.get("platform", "android"), "liveId": source.get("liveId"),
                   "live3dAssetId": source.get("assetId"), "stageText": source.get("stageText"), "deckLiveMasterId": source.get("liveId")},
        "client": {"package": None, "apkName": None, "device": "synthetic"},
        "screen": {"width": width, "height": height, "orientation": {"v": 3, "n": "LandscapeLeft"} if width >= height else {"v": 1, "n": "Portrait"},
                   "landscape": width >= height, "wmSize": f"{width}x{height}"},
        "fovmod": {"prefs": {"minWord": 506269697, "maxWord": 506335234}, "decoded": {"min": 0.75, "max": 1.0},
                   "sfovrw22": {"min": 0.75, "max": 1.0}, "readAt": "dump-start"},
        "quality": {"holder": "synthetic", "values": quality_values or {}},
        "limits": {"synthetic": True},
        "keys": None,
        "probe": {"classesFound": [], "classesMissing": [], "file": None},
    }
    header.update(extra or {})
    return header


def clock(t, delta, seq):
    return {"directorTime": t, "frameCount": 1000 + seq, "unityTime": 100 + t, "unscaledTime": 100 + t, "deltaTime": delta,
            "timeScale": 1, "realtimeSinceStartup": 200 + t, "musicTime": t * 1000, "musicPlaying": True}  # LiveMusicMachine ms


def envelope(rid, kind, seq, t, delta, extra=None):
    record = {"id": rid, "kind": kind, "seq": seq, "clock": clock(t, delta, seq),
              "clockEnd": {"directorTime": t, "frameCount": 1000 + seq, "realtimeSinceStartup": 200 + t},
              "cost": {"elapsedMs": 0, "calls": 0, "objects": 0, "truncated": False, "truncatedSections": []}, "nonFinite": []}
    record.update(extra or {})
    return record


def skeleton(times, full_at=(), parts=DEFAULT_PARTS, delta=1 / 15, source=None, screen=(1280, 720), duration=None, quality_mode=None):
    """A game-style document holding only record envelopes at the given director times."""
    records, seq = [], 0
    for index, t in enumerate(sorted(times)):
        seq += 1
        records.append(envelope(f"f{index + 1:04d}", "frame", seq, t, delta))
    for pass_index, t in enumerate(sorted(full_at)):
        for part in parts:
            seq += 1
            records.append(envelope(f"p{pass_index}-{part}-00", "full", seq, t, delta,
                                    {"pass": pass_index, "part": part, "chunk": 0, "cursor": {}, "next": None}))
    records.sort(key=lambda record: (record["clock"]["directorTime"], record["seq"]))
    for seq, record in enumerate(records, 1):  # the game numbers records in sampling order
        record["seq"] = seq
        record["clock"]["frameCount"] = record["clockEnd"]["frameCount"] = 1000 + seq
    quality = {"Quality": {"v": quality_mode, "n": None}} if isinstance(quality_mode, int) else None
    header = game_header(source or {}, screen, quality, producer="mv_runtime_synthetic.py skeleton",
                         extra={"note": "Synthetic time skeleton: record envelopes only, no game values."})
    return {"schema": SCHEMA, "side": "game", "header": header, "records": records,
            "trailer": {"records": {"frame": len(times), "full": len(records) - len(times)}, "stopReason": "synthetic",
                        "coverage": {"directorFirst": min(times), "directorLast": max(times), "duration": duration}, "truncation": None}}


def _position(value):
    return Conventions.position(value) if isinstance(value, list) and len(value) == 3 and None not in value else value


def _rotation(value):
    return Conventions.quaternion(value) if isinstance(value, list) and len(value) == 4 and None not in value else value


def _instance_id(text):
    return -(zlib.crc32(text.encode("utf-8")) & 0x3FFFFFFF) - 1


def _game_camera(camera, hypothesis, screen):
    transform = camera.get("transform") or {}
    rig_position = Conventions.position(transform["position"])
    rig_rotation = Conventions.quaternion(transform["rotation"])
    return {"key": camera["key"], "role": camera.get("role"), "path": "/EntryPoint/Live/Cameras/MainCamera/Camera",
            "enabled": True, "isActiveAndEnabled": True, "activeInHierarchy": True,
            "fieldOfView": camera["fieldOfView"], "aspect": camera["aspect"], "nearClipPlane": camera.get("nearClipPlane"),
            "farClipPlane": camera.get("farClipPlane"), "orthographic": False, "projection": list(camera["projection"]),
            "worldToCamera": Conventions.world_to_camera(camera["worldToCamera"], hypothesis),
            "pixelWidth": screen[0], "pixelHeight": screen[1], "targetTexture": None, "cullingMask": MAIN_CULLING_MASK,
            "transform": {"position": rig_position, "rotation": Conventions.camera_component_rotation(rig_rotation, hypothesis),
                          "lossyScale": [1, 1, 1]},
            "rig": {"path": "/EntryPoint/Live/Cameras/MainCamera", "position": list(rig_position), "rotation": list(rig_rotation)}}


def _mirror_frame(record, editor, hypothesis, screen, duration):
    result = {"scene": {"name": "LiveMv", "width": screen[0], "height": screen[1], "orientation": {"v": 3, "n": "LandscapeLeft"}},
              "directors": [{"key": "director:/EntryPoint/Live/Director", "path": "/EntryPoint/Live/Director", "main": True, "enabled": True,
                             "time": record["clock"]["directorTime"], "duration": duration, "state": {"v": 1, "n": "Playing"}}]}
    cameras = [_game_camera(camera, hypothesis, screen) for camera in editor.get("cameras") or []
               if camera.get("key") == "camera:main" and camera.get("liveShot", True) and camera.get("transform")]
    result["cameras"] = cameras
    result["correctors"] = [{"key": corrector["key"], "path": "/EntryPoint/Live/Cameras/MainCamera/Camera", "enabled": True,
                             "mode": {"v": 1, "n": None}, "correction": corrector["correction"], "defaultOrthographicSize": 5,
                             "target": {"cameraKey": "camera:main"}, "fields": {}}
                            for corrector in editor.get("correctors") or []]
    result["cameraWork"] = [{"key": work["key"], "path": "/EntryPoint/Live/Cameras/MainCamera", "class": "LLAS.Scene.Live.Components.LiveCoreCameraWork",
                             "fields": {"fieldOfView": {"t": "f32", "v": work["authoredFov"]}}} for work in editor.get("cameraWork") or []]
    result["globals"] = {key: {"f": value["f"], "v": [value["f"], 0, 0, 0]} for key, value in (editor.get("globals") or {}).items()
                         if isinstance(value, dict)}
    result["renderSettings"] = {"fog": False, "ambientIntensity": 1}
    result["lights"] = []
    result["members"] = [{"slot": member.get("slot"), "formationPosition": member.get("slot"), "memberId": member.get("memberId"),
                          "suitId": member.get("costumeId"), "path": f"/EntryPoint/Live/Members/Member{member.get('slot')}", "active": True}
                         for member in editor.get("members") or [] if "memberId" in member]
    result["anchors"] = [{"key": anchor["key"], "position": Conventions.position(anchor["position"])} for anchor in editor.get("anchors") or []]
    return result


def _member_root(slot):
    return f"/EntryPoint/Live/Members/Member{slot}/{MEMBER_MODEL}"


def game_renderer_path(entry):
    """The game GameObject path of an editor renderer entry {key, scope, mesh, path}.

    An editor path (prefab root first) maps below the scope root; the effect prefab root
    is the Effect object itself. A flattened editor renderer (path null) becomes the mesh
    name under the scope root, with the schema's '#k' suffix for a repeated name."""
    scope, path = entry.get("scope"), entry.get("path")
    member = scope[len("member"):] if isinstance(scope, str) and scope.startswith("member") else None
    root = _member_root(member) if member else EFFECT_ROOT if scope == "effect" else STAGE_ROOT if scope == "stage" else "/Synthetic"
    if isinstance(path, str):
        below = Conventions.editor_relative_path(path) if scope in ("effect",) or member else path
        return f"{root}/{below}" if below else root
    index = str(entry.get("key") or "").rpartition("#")
    name = entry.get("mesh") or "renderer"
    if index[0] and index[2].isdigit():
        name += f"#{index[2]}"
    return f"{root}/{name}"


def renderer_index(editor_doc):
    """Editor renderer key -> {key, scope, mesh, path}, from renderers parts and census nodes."""
    index = {}
    for record in editor_doc.get("records") or []:
        entries = list(record.get("renderers") or []) + [node for node in (record.get("census") or {}).get("nodes") or []
                                                         if node.get("kind") == "renderer"]
        for entry in entries:
            key = entry.get("key")
            if not key or key in index:
                continue
            parsed = Conventions.renderer_scope_mesh(key) or (None, None)
            index[key] = {"key": key, "scope": entry.get("scope") or parsed[0], "mesh": entry.get("mesh", parsed[1]), "path": entry.get("path")}
    return index


def _game_key(editor_key, renderers):
    entry = renderers.get(editor_key)
    if entry is None:
        parsed = Conventions.renderer_scope_mesh(editor_key) or ("other", editor_key)
        entry = {"key": editor_key, "scope": parsed[0], "mesh": parsed[1], "path": None}
    return "renderer:" + game_renderer_path(entry)


def _mirror_part(part, editor, renderers):
    if part == "renderers":
        result = []
        for item in editor.get("renderers") or []:
            path = game_renderer_path(item)
            culled = item.get("culled") is True
            result.append({"key": "renderer:" + path, "path": path, "scope": item["scope"], "mesh": item["mesh"],
                           "class": item.get("class"), "instanceId": _instance_id(item["key"]), "enabled": item["visible"],
                           "isVisible": item["visible"] and not culled, "activeInHierarchy": item["visible"],
                           "layer": INVISIBLE_LAYER if culled else 0,
                           "transform": {"position": _position(item["transform"]["position"]),
                                         "rotation": _rotation(item["transform"]["rotation"]), "lossyScale": item["transform"]["lossyScale"]},
                           "materials": [{"slot": slot["slot"], "instanceId": _instance_id(f"{item['key']}#{slot['slot']}"), "name": slot["name"],
                                          "shader": slot.get("kind")} for slot in item.get("materials") or []]})
        return result
    if part == "materials":
        materials = []
        for item in editor.get("materials") or []:
            properties = {}
            for name, prop in (item.get("properties") or {}).items():
                unity = Conventions.material_property(name)
                if unity:
                    properties[unity] = {key: value for key, value in prop.items() if key in ("t", "v", "st")}
                    if isinstance(prop.get("st"), list) and len(prop["st"]) == 4 and prop.get("stFrom") in Conventions.V_FLIPPED_ST:
                        properties[unity]["st"] = Conventions.texture_st(prop["st"])
            materials.append({"instanceId": _instance_id(item["key"]), "name": item.get("name"), "shader": item.get("kind"),
                              "usedBy": [f"{_game_key(item['renderer'], renderers)}#{item['slot']}"], "properties": properties, "missing": []})
        return materials
    if part == "stageNodes":
        return [{"binding": node["binding"], "relPath": None, "crc": node["crc"], "path": f"{node['binding']}/#{node['crc']}",
                 "activeSelf": node.get("activeSelf"), "activeInHierarchy": node["visible"],
                 "position": _position(node["position"]), "rotation": _rotation(node["rotation"]),
                 "lossyScale": node["lossyScale"]} for node in editor.get("stageNodes") or []]
    if part == "members":
        return [{"slot": member["slot"], "path": f"/EntryPoint/Live/Members/Member{member['slot']}", "rootPath": _member_root(member["slot"]),
                 "bones": [{"key": bone["key"], "position": _position(bone["position"]), "rotation": _rotation(bone["rotation"]),
                            "lossyScale": bone["lossyScale"], "localPosition": _position(bone["localPosition"]),
                            "localRotation": _rotation(bone["localRotation"])} for bone in member.get("bones") or []],
                 "blendShapes": [{"rendererKey": _game_key(morph["rendererKey"], renderers),
                                  "weights": {name: Conventions.blend_weight(weight, morph.get("unit")) for name, weight in morph["weights"].items()}}
                                 for morph in member.get("morphs") or []]}
                for member in editor.get("members") or [] if isinstance(member, dict) and "bones" in member]
    if part == "springs":
        springs = editor.get("springs")
        result = []
        for manager in springs if isinstance(springs, list) else []:
            bones = []
            for bone in manager.get("bones") or []:
                _, slot, below = bone["key"].split(":", 2)  # member:<slot>:<rig path below the BodyPartManager root>
                path = f"{_member_root(slot)}/{below}" if below else _member_root(slot)
                bones.append({"key": "spring:" + path, "path": path, "localRotation": _rotation(bone["localRotation"])})
            slot = manager["managerKey"].rpartition("member")[2]
            result.append({"managerKey": "spring:" + _member_root(slot), "path": _member_root(slot), "fields": {}, "bones": bones})
        return result
    if part == "post":
        post = editor.get("post") or {}
        return {"enablePostEffect": post.get("applied"), "holders": []}
    if part == "quality":
        quality = editor.get("quality") or {}
        return {"holder": "synthetic", "values": {Conventions.quality_name(key): value for key, value in (quality.get("values") or {}).items()}}
    if part == "census":
        return {"roots": ["/EntryPoint"], "nodes": []}
    if part in ("particles", "lightingRefs"):
        return []
    return None


def game_from_editor(editor_doc, hypothesis="H180", source_phase=0):
    """The game document that agrees exactly with the editor (Conventions inverses only).

    Records are taken from editor phase `source_phase` while keeping the game director
    time, so a non-zero value simulates a game that runs that many frames ahead."""
    editor_doc = copy.deepcopy(editor_doc)  # the game document must not share lists with the editor's
    header = editor_doc["header"]
    renderers = renderer_index(editor_doc)
    screen = ((header.get("screen") or {}).get("width") or 1280, (header.get("screen") or {}).get("height") or 720)
    quality = {Conventions.quality_name(key): value for key, value in ((header.get("quality") or {}).get("values") or {}).items()}
    duration = None
    records = []
    sources = [record for record in editor_doc["records"] if record.get("phase") == source_phase]
    for record in sources:
        for director in record.get("directors") or []:
            duration = director.get("duration") or duration
    for seq, record in enumerate(sorted(sources, key=lambda item: (item["clock"]["sourceDirectorTime"], item["id"])), 1):
        t, delta = record["clock"]["sourceDirectorTime"], record["clock"].get("deltaTime") or 1 / 15
        extra = {}
        if record["kind"] == "full":
            extra = {"pass": record.get("pass"), "part": record["part"], "chunk": record.get("chunk", 0), "cursor": {}, "next": None}
        game = envelope(record["sourceRecord"], record["kind"], seq, t, delta, extra)
        if record["kind"] == "frame":
            game.update(_mirror_frame(game, record, hypothesis, screen, duration))
        else:
            value = _mirror_part(record["part"], record, renderers)
            if value is not None:
                game[record["part"]] = value
        records.append(game)
    source = dict(header.get("source") or {})
    doc = {"schema": SCHEMA, "side": "game",
           "header": game_header(source, screen, quality, producer="mv_runtime_synthetic.py mirror",
                                 extra={"mirroredFrom": {"sha256": (editor_doc.get("_source") or {}).get("sha256"), "hypothesis": hypothesis,
                                                         "sourcePhase": source_phase}}),
           "records": records,
           "trailer": {"records": {"frame": sum(1 for r in records if r["kind"] == "frame"), "full": sum(1 for r in records if r["kind"] == "full")},
                       "stopReason": "synthetic", "truncation": None, "fovmodEnd": {"sfovrw22": {"min": 0.75, "max": 1.0}, "readAt": "dump-end"}}}
    return doc


def _main(record):
    return next((camera for camera in record.get("cameras") or [] if camera.get("key") == "camera:main"), None)


def perturb(doc, fov=0.0, camera_move=0.0, material_delta=0.0, hide=False):
    """Inject known discrepancies; returns (document, manifest of what changed)."""
    doc = copy.deepcopy(doc)
    manifest = {"fovDeltaDeg": fov, "cameraMoveM": camera_move, "materialDelta": material_delta, "hidden": None, "material": None,
                "expected": {}}
    frames = [record for record in doc["records"] if record["kind"] == "frame" and _main(record)]
    for record in frames:
        camera = _main(record)
        if fov:
            camera["fieldOfView"] += fov
            focal = 1 / math.tan(math.radians(camera["fieldOfView"]) / 2)
            camera["projection"][5] = focal
            camera["projection"][0] = focal / camera["aspect"]
            for work in record.get("cameraWork") or []:
                for field in (work.get("fields") or {}).values():
                    if isinstance(field, dict) and field.get("t") == "f32":
                        field["v"] += fov
        if camera_move:
            move = [camera_move, 0.0, 0.0]
            for holder in (camera["rig"], camera["transform"]):
                holder["position"] = [value + delta for value, delta in zip(holder["position"], move)]
            w = camera["worldToCamera"]
            for row in range(3):
                w[12 + row] -= sum(w[column * 4 + row] * move[column] for column in range(3))
    if fov or camera_move:
        manifest["expected"]["camera"] = (["fovAbsDeg"] if fov else []) + (["rigPositionM"] if camera_move else [])
    if material_delta:
        for record in doc["records"]:
            if record.get("part") != "materials":
                continue
            target = next(((material, name) for material in record.get("materials") or []
                           for name, prop in (material.get("properties") or {}).items()
                           if prop.get("t") == "color" and isinstance(prop.get("v"), list) and len(prop["v"]) >= 3 and material.get("usedBy")), None)
            if target:
                material, name = target
                material["properties"][name]["v"][0] += material_delta
                key = "material:" + material["usedBy"][0]
                manifest["material"] = {"record": record["id"], "key": key, "property": name}
                manifest["expected"]["materials"] = {"key": key, "field": name}
                break
    if hide:
        # Prefer a visible stage-effect renderer other than the one whose material changed.
        changed = (manifest["material"] or {}).get("key", "")
        candidates = [renderer["key"] for record in doc["records"] if record.get("part") == "renderers"
                      for renderer in record.get("renderers") or []
                      if renderer.get("enabled") and renderer.get("activeInHierarchy") and not changed.startswith(f"material:{renderer['key']}#")]
        scopes = {renderer["key"]: renderer.get("scope") for record in doc["records"] if record.get("part") == "renderers"
                  for renderer in record.get("renderers") or []}
        chosen = next((key for key in candidates if scopes.get(key) == "effect"), next(iter(candidates), None))
        if chosen:
            for record in doc["records"]:
                for renderer in record.get("renderers") or [] if record.get("part") == "renderers" else []:
                    if renderer["key"] == chosen:
                        renderer.update(enabled=False, activeInHierarchy=False, isVisible=False)
            manifest["hidden"] = chosen
            manifest["expected"]["visibility"] = {"key": chosen}
    doc["header"]["producer"]["perturbed"] = {key: value for key, value in manifest.items() if key != "expected"}
    return doc, manifest


def job_log(doc, chunk=2000, timestamp="2026-11-23T12:00:00.0000000Z", probe=True):
    """Schema section 8 transport: rtdump-core (frames + trailer), rtdump-full (full records) and,
    like the game sampler, rtdump-probe (the probe's class inventory, not a dump document)."""
    lines = []
    clean = {key: value for key, value in doc.items() if not key.startswith("_")}
    blobs = [("rtdump-core", dict(clean, records=[r for r in clean["records"] if r["kind"] == "frame"])),
             ("rtdump-full", dict(clean, records=[r for r in clean["records"] if r["kind"] != "frame"], trailer=None))]
    if probe:
        blobs.append(("rtdump-probe", {"chunks": [{"classes": [{"key": "Camera", "found": True, "fullName": "UnityEngine.Camera",
                                                                "fields": []}]}],
                                       "classesFound": ["Camera"], "classesMissing": [], "layoutSelfCheck": None, "resolved": {}}))
    for name, part in blobs:
        data = gzip.compress(json.dumps(part, separators=(",", ":")).encode("utf-8"), 9, mtime=0)
        text = base64.b64encode(data).decode("ascii")
        pieces = [text[index:index + chunk] for index in range(0, len(text), chunk)]
        index = {"name": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "chunks": len(pieces),
                 "records": len(part["records"]) if "records" in part else None, "schema": SCHEMA}
        lines.append(f"{timestamp} @@RTDUMP-INDEX {json.dumps(index, separators=(',', ':'))}")
        lines.append(f"{timestamp} @@RTDUMP-BEGIN {name}")
        lines += [f"{timestamp} @@{piece}" for piece in pieces]
        lines.append(f"{timestamp} @@RTDUMP-END {name}")
    lines.append(f"{timestamp} @@RTDUMP-SUMMARY {{\"status\":\"SYNTHETIC\"}}")
    return "\n".join(lines) + "\n"


def _floats(text):
    return [float(value) for value in text.split(",") if value.strip()]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    one = sub.add_parser("skeleton")
    one.add_argument("--times", required=True)
    one.add_argument("--full-at", default="")
    one.add_argument("--parts", default=",".join(DEFAULT_PARTS))
    one.add_argument("--delta", type=float, default=1 / 15)
    one.add_argument("--manifest", help="frame manifest whose source is recorded in the header")
    one.add_argument("--width", type=int, default=1280)
    one.add_argument("--height", type=int, default=720)
    one.add_argument("--out", required=True)
    two = sub.add_parser("mirror")
    two.add_argument("--editor", required=True)
    two.add_argument("--hypothesis", default="H180", choices=Conventions.HYPOTHESES)
    two.add_argument("--source-phase", type=int, default=0)
    two.add_argument("--out", required=True)
    three = sub.add_parser("perturb")
    three.add_argument("--game", required=True)
    three.add_argument("--fov", type=float, default=0.0)
    three.add_argument("--camera-move", type=float, default=0.0)
    three.add_argument("--material-delta", type=float, default=0.0)
    three.add_argument("--hide", default="false")
    three.add_argument("--manifest")
    three.add_argument("--out", required=True)
    four = sub.add_parser("joblog")
    four.add_argument("--game", required=True)
    four.add_argument("--out", required=True)
    arguments = parser.parse_args(argv)
    if arguments.command == "skeleton":
        manifest = json.loads(Path(arguments.manifest).read_text("utf-8")) if arguments.manifest else {}
        doc = skeleton(_floats(arguments.times), _floats(arguments.full_at), [part for part in arguments.parts.split(",") if part],
                       arguments.delta, manifest.get("source", {}), (arguments.width, arguments.height),
                       quality_mode=(manifest.get("quality") or {}).get("mode"))
        write_dump(doc, arguments.out)
        print(json.dumps({"out": arguments.out, "records": len(doc["records"])}))
    elif arguments.command == "mirror":
        doc = game_from_editor(load_dump(arguments.editor), arguments.hypothesis, arguments.source_phase)
        write_dump(doc, arguments.out)
        print(json.dumps({"out": arguments.out, "records": len(doc["records"])}))
    elif arguments.command == "perturb":
        doc, manifest = perturb(load_dump(arguments.game), arguments.fov, arguments.camera_move, arguments.material_delta,
                                arguments.hide.lower() in ("1", "true", "yes"))
        write_dump(doc, arguments.out)
        if arguments.manifest:
            Path(arguments.manifest).write_text(json.dumps(manifest, indent=1) + "\n", "utf-8")
        print(json.dumps(manifest))
    else:
        Path(arguments.out).write_text(job_log(load_dump(arguments.game)), "utf-8")
        print(json.dumps({"out": arguments.out}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
