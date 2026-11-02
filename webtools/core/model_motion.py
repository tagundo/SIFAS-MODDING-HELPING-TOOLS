"""Read-only, bounded import of the verified SIFAS suit-preview resource.

Only the game's UiNaviMotionKey.SuitPreview (=1) recipe is supported. Encrypted
inputs are decrypted into a private temporary directory, never over user files.
"""
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import re
import sqlite3
import tempfile

MAX_BYTES = 8 * 1024 * 1024
MAX_UNPACKED = 32 * 1024 * 1024
KNOWN_PREVIEWS = {
    "96ada81d0b8f35573fa81e0a3830b018a1d46ff26fff778f3be0a0deed618ebe": {
        "size": 8826, "assetName": "motion/ch0301_gen_preview1_l.unity3d",
        "clipName": "ch0301_GEN_preview1_L", "channels": 58,
    }
}
_PACK = re.compile(r"^[a-zA-Z0-9_-]{1,80}$")


def source_id(path):
    return hashlib.sha256(os.path.realpath(path).encode("utf-8", "surrogatepass")).hexdigest()[:24]


def _check(deadline):
    from .model_viewer import _remaining
    _remaining(deadline)


class MotionInputs:
    def __init__(self, paths, context, deadline):
        self.paths, self.context, self.deadline = list(paths), dict(context or {}), deadline
        self.origins, self.verified, self._temporary, self._catalog = {}, [], None, None

    def close(self):
        if self._temporary is not None:
            self._temporary.cleanup()

    def descriptors(self, deadline=None):
        deadline = self.deadline if deadline is None else deadline
        if self._catalog is not None:
            return self._catalog
        root = self.context.get("repo_root")
        self._catalog = []
        if not root:
            return self._catalog
        import llas_asset_extractor as extractor
        asset_keys = set()
        for region in ("gl", "jp"):
            path = Path(root) / "assets" / "db" / region / "masterdata.db"
            if not path.is_file():
                continue
            with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
                try:
                    asset_keys.update(row[0] for row in db.execute("SELECT animation_clip_path FROM m_ui_navi_motion WHERE motion_key=1"))
                except sqlite3.Error:
                    pass
        seen = set()
        for path in extractor.list_asset_dbs(root):
            _check(deadline)
            with sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True) as db:
                for key in sorted(asset_keys):
                    try:
                        rows = db.execute("SELECT asset_path,pack_name,head,size,key1,key2 FROM navi_motion WHERE asset_path=?", (key,)).fetchall()
                    except sqlite3.Error:
                        continue
                    for row in rows[:4]:
                        if row in seen:
                            continue
                        seen.add(row)
                        try:
                            size = db.execute("SELECT file_size FROM m_asset_package_mapping WHERE pack_name=? LIMIT 1", (row[1],)).fetchone()
                        except sqlite3.Error:
                            size = None
                        self._catalog.append(dict(zip(("asset_path", "pack_name", "head", "size", "key1", "key2"), row), pack_size=int(size[0]) if size else None))
                        if len(self._catalog) >= 16:
                            return self._catalog
        return self._catalog

    def _register(self, path, original, data, deadline=None):
        deadline = self.deadline if deadline is None else deadline
        _check(deadline)
        recipe = KNOWN_PREVIEWS.get(hashlib.sha256(data).hexdigest())
        if recipe is None:
            return False
        from .model_viewer import _environment
        env = _environment([path], deadline)
        clips = [obj for obj in env.objects if obj.type.name == "AnimationClip"]
        names = [obj.peek_name() for obj in env.objects if obj.type.name == "AssetBundle"]
        if len(clips) != 1 or clips[0].peek_name() != recipe["clipName"] or (recipe["assetName"] and recipe["assetName"] not in names):
            raise ValueError("The suit-preview resource does not match its verified contents.")
        record = dict(recipe, path=path, sourceId=source_id(path), sourceHash=hashlib.sha256(data).hexdigest(), sourceName=os.path.basename(original))
        if not any(item["sourceId"] == record["sourceId"] for item in self.verified):
            self.verified.append(record)
        return True

    def _decrypt(self, path, descriptor, deadline):
        _check(deadline)
        name, head, size = descriptor["pack_name"], descriptor["head"], descriptor["size"]
        expected = descriptor["pack_size"]
        length = os.path.getsize(path)
        if not _PACK.fullmatch(name) or not isinstance(head, int) or not isinstance(size, int) or head < 0 or not 0 < size <= MAX_BYTES \
                or not head + size <= length <= MAX_BYTES or (expected is not None and length != expected):
            raise ValueError("The SIFAS suit-preview pack is incomplete or exceeds the preview limits.")
        with open(path, "rb") as handle:
            handle.seek(head)
            data = bytearray(handle.read(size))
        if len(data) != size:
            raise ValueError("The SIFAS suit-preview pack is truncated.")
        import llas_asset_extractor as extractor
        extractor.decrypt_section(data, extractor.FIXED_KEY0, descriptor["key1"], descriptor["key2"])
        from .model_viewer import _preflight_bundle
        if _preflight_bundle(data) > MAX_UNPACKED:
            raise ValueError("The suit-preview resource exceeds the animation memory limit.")
        if hashlib.sha256(data).hexdigest() not in KNOWN_PREVIEWS:
            raise ValueError("The encrypted file does not match the verified SIFAS suit-preview resource.")
        if self._temporary is None:
            from .model_faces import _cache_root
            root = self.context.get("cache_dir")
            if not root:
                raise ValueError("A private viewer cache is required to import an encrypted animation pack.")
            root = _cache_root(root)
            root.mkdir(parents=True, exist_ok=True)
            self._temporary = tempfile.TemporaryDirectory(prefix="viewer-motion-", dir=root)
        output = os.path.join(self._temporary.name, "motion_" + str(len(self.origins)) + ".unity")
        with open(output, "xb") as handle:
            handle.write(data)
        self.origins[output] = path
        self._register(output, path, data, deadline)
        return output

    def selected(self):
        from .viewer_archive import _model_header
        result = []
        for path in self.paths:
            _check(self.deadline)
            size = os.path.getsize(path)
            with open(path, "rb") as handle:
                header = handle.read(48)
                if _model_header(header, size):
                    if size in {entry["size"] for entry in KNOWN_PREVIEWS.values()}:
                        handle.seek(0)
                        self._register(path, path, handle.read(MAX_BYTES + 1))
                    result.append(path)
                    continue
            candidates = [row for row in self.descriptors() if row["pack_name"] == os.path.basename(path)]
            if not candidates:
                raise ValueError("Choose an extracted Unity animation or a recognized original SIFAS suit-preview pack.")
            for descriptor in candidates:
                try:
                    result.append(self._decrypt(path, descriptor, self.deadline))
                    break
                except ValueError:
                    continue
            else:
                raise ValueError("The suit-preview pack could not be decrypted with the installed game asset databases.")
        self.paths = result
        return result

    def _fully_bound(self, path, rig, deadline):
        from .model_viewer import _environment, _Scene
        from .model_animation import decode_clip, _nodes
        record = next(item for item in self.verified if item["path"] == path)
        scene = _Scene(_environment([path], deadline), deadline)
        clip = next(obj for obj in scene.env.objects if obj.type.name == "AnimationClip")
        decoded = decode_clip(scene.tree(clip), deadline)
        return (not decoded["unsupported"] and len(decoded["tracks"]) == record["channels"]
                and all(track["kind"] in ("translation", "rotation", "euler", "scale")
                        and len(set(_nodes(rig.node_bindings, track["path"]))) == 1 for track in decoded["tracks"]))

    def automatic(self, rig, loaded, deadline):
        if self.verified or len(loaded) >= 8 or not self.context.get("repo_root"):
            return []
        import llas_asset_extractor as extractor
        roots = list(self.context.get("pack_roots", [])) + list(self.context.get("library_roots", []))
        roots.extend(os.path.dirname(path) for path in self.paths)
        roots.extend(os.path.dirname(os.path.realpath(path)) for path in self.context.get("origins", {}).values())
        if os.environ.get("SUKUSTA_DIR"):
            roots.append(os.path.join(os.environ["SUKUSTA_DIR"], "packs"))
        roots.append(extractor.COPIED_PACKS_DIR)
        if self.context.get("repo_root"):
            roots.extend((self.context["repo_root"], os.path.join(self.context["repo_root"], "static")))
        roots.extend(path for path, state in extractor.detect_game_candidates() if state == "found")
        attempted = set()
        for descriptor in self.descriptors(deadline):
            name = descriptor["pack_name"]
            if not isinstance(name, str) or not _PACK.fullmatch(name):
                continue
            for root in dict.fromkeys(os.path.realpath(path) for path in roots):
                for relative in (name, "pkg" + name[0] + "/" + name, "pak" + name[0] + "/" + name, "files/pkg" + name[0] + "/" + name):
                    _check(deadline)
                    path = os.path.realpath(os.path.join(root, relative))
                    if path in attempted or not path.startswith(root + os.sep) or not os.path.isfile(path):
                        continue
                    attempted.add(path)
                    try:
                        staged = self._decrypt(path, descriptor, deadline)
                        if self._fully_bound(staged, rig, deadline):
                            return [staged]
                    except (ValueError, OSError):
                        continue
        return []

    def promote(self, metadata):
        for record in self.verified:
            for clip in metadata.get("clips", []):
                if clip.get("sourceId") == record["sourceId"] and clip.get("sourceName") == record["clipName"] \
                        and clip.get("sourceHash") == record["sourceHash"] \
                        and clip.get("bindingComplete") is True and clip.get("channels") == record["channels"] \
                        and clip.get("sourceTracks") == record["channels"]:
                    metadata["previewMotion"] = {"kind": "sifas_suit_preview", "verified": True, "name": clip["name"],
                                                 "sourceName": record["sourceName"], "assetName": record["assetName"]}
                    return


@contextmanager
def prepare_motion_inputs(paths, context, deadline):
    stage = MotionInputs(paths, context, deadline)
    try:
        stage.selected()
        yield stage
    finally:
        stage.close()
