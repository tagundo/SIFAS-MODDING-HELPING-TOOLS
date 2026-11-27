"""MV-only song registration flow (webtools/core/mv_studio_register.py) on synthetic game databases.

The Elichika store (mv_studio_live, database_maintenance) runs for real when the Elichika
server app is importable: set ELICHIKA_DIR, or run from Elichika's modtools submodule.
Native timelines are synthetic JSON stand-ins ("UnityFS" + JSON); the optional real-sample
tests bake real 12035 timelines when ELICHIKA_STUDIO_TIMELINE_DIR holds them.
No game data is stored in this file.
"""
import ast
import base64
from contextlib import contextmanager, closing
import copy
import hashlib
import http.client
import io
import json
import os
from pathlib import Path
import sqlite3
import struct
import sys
import tempfile
import threading
import unittest
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def _elichika_dir():
    for candidate in (os.environ.get("ELICHIKA_DIR"), REPO.parent):
        if candidate and (Path(candidate) / "mv_studio_live.py").is_file():
            return Path(candidate).resolve()
    return None


ELICHIKA = _elichika_dir()
if ELICHIKA is not None and str(ELICHIKA) not in sys.path:
    sys.path.append(str(ELICHIKA))
try:
    import costume_management  # noqa: E402
    import database_maintenance  # noqa: E402
    import mv_studio_live  # noqa: E402
    import mv_studio_manage  # noqa: E402
    import mv_studio_native_assets as native  # noqa: E402
except ImportError:
    mv_studio_live = None

from webtools import i18n  # noqa: E402
from webtools.core import mv_studio, mv_studio_register as register, mv_studio_timeline  # noqa: E402

# The real server session and job lifecycle (Case replaces both with stand-ins).
REAL_SERVER_SESSION, REAL_LIFECYCLE = register._server_session, register._lifecycle
# The real native timeline reader and writer (Case replaces both with JSON stand-ins).
REAL_PARSE, REAL_EXPORT = mv_studio_timeline.parse_timeline, mv_studio_timeline.export_timeline
REAL_BLOB_PLATFORM = register._blob_platform
REAL_VALIDATE = native._validate_timeline if mv_studio_live is not None else None

SAMPLES = Path(os.environ.get("ELICHIKA_STUDIO_TIMELINE_DIR", "/unavailable-studio-samples"))
NEEDS_STORE = unittest.skipUnless(mv_studio_live is not None, "The Elichika server app is not importable")
TIMELINE_SIZE = 4096

MASTER = """
CREATE TABLE m_live (live_id INTEGER NOT NULL PRIMARY KEY, is_2d_live INTEGER NOT NULL, music_id INTEGER NOT NULL,
 bgm_path TEXT NOT NULL, chorus_bgm_path TEXT NOT NULL, live_member_mapping_id INTEGER NOT NULL, name TEXT NOT NULL,
 pronunciation TEXT, member_group INTEGER NOT NULL, member_unit INTEGER, original_deck_name TEXT, copyright TEXT NOT NULL,
 source TEXT, jacket_asset_path TEXT NOT NULL, background_asset_path TEXT NOT NULL, display_order INTEGER NOT NULL,
 UNIQUE (display_order));
INSERT INTO m_live VALUES
 (21,0,21,'music_0021','music_0021_SABI',11,'k.song_name_21','k.song_pron_21',2,NULL,'k.deck','k.song_copyright_21',
  'k.src','jk21','bg21',7),
 (22,0,22,'music_0022','music_0022_SABI',12,'k.song_name_22',NULL,2,NULL,NULL,'k.song_copyright_22',NULL,'jk22','bg22',8);
CREATE TABLE m_live_3d_asset (id INTEGER NOT NULL PRIMARY KEY, timeline TEXT NOT NULL, live_stage_master_id INTEGER NOT NULL,
 stage_effect_asset_path TEXT NOT NULL, live_prop_skeleton_asset_path TEXT, quality_setitng_set_id INTEGER NOT NULL,
 shader_variant_asset_path TEXT);
INSERT INTO m_live_3d_asset VALUES (2101,'A2101',101,'E2101',NULL,3,NULL),(2201,'A2201',102,'E2201',NULL,3,NULL);
CREATE TABLE m_live_mv (live_id INTEGER NOT NULL, live_stage_master_id INTEGER NOT NULL, position INTEGER NOT NULL,
 live_3d_asset_master_id INTEGER NOT NULL, PRIMARY KEY (live_id, live_stage_master_id), UNIQUE (live_id, position));
INSERT INTO m_live_mv VALUES (21,101,1,2101),(22,102,1,2201);
CREATE TABLE m_live_stage (id INTEGER NOT NULL PRIMARY KEY, stage_model_asset_path TEXT NOT NULL, stage_name TEXT,
 scene_name TEXT);
INSERT INTO m_live_stage VALUES (101,'s101','k.stage_name_101','scene101'),(102,'s102',NULL,'scene102');
CREATE TABLE m_live_visible_definition (live_m_id INTEGER NOT NULL PRIMARY KEY, safe_swing_bone INTEGER,
 live_mixer_base_mode INTEGER, live_enable_skin_merge INTEGER);
CREATE TABLE m_live_difficulty (live_difficulty_id INTEGER NOT NULL PRIMARY KEY, live_id INTEGER NOT NULL,
 live_3d_asset_master_id INTEGER, live_difficulty_type INTEGER NOT NULL, unlock_pattern INTEGER NOT NULL,
 target_voltage INTEGER NOT NULL, consumed_lp INTEGER NOT NULL, difficulty_const_master_id INTEGER NOT NULL,
 updated_at INTEGER NOT NULL);
INSERT INTO m_live_difficulty VALUES (21301,21,2101,30,1,5000,15,21301,0),(22301,22,2201,30,1,6000,15,22301,0);
CREATE TABLE m_live_difficulty_const (id INTEGER NOT NULL PRIMARY KEY, sp_gauge_length INTEGER NOT NULL,
 note_stamina_reduce INTEGER NOT NULL);
INSERT INTO m_live_difficulty_const VALUES (21301,6000,20),(22301,6100,21);
CREATE TABLE m_live_difficulty_mission (live_difficulty_master_id INTEGER NOT NULL, position INTEGER NOT NULL,
 target_type INTEGER NOT NULL, target_value INTEGER NOT NULL, PRIMARY KEY (live_difficulty_master_id, position));
INSERT INTO m_live_difficulty_mission VALUES (21301,1,1,1);
CREATE TABLE m_live_difficulty_gimmick (id INTEGER NOT NULL PRIMARY KEY, live_difficulty_master_id INTEGER NOT NULL,
 trigger_type INTEGER NOT NULL, skill_master_id INTEGER NOT NULL, name TEXT NOT NULL, description TEXT NOT NULL);
CREATE TABLE m_live_difficulty_note_gimmick (live_difficulty_id INTEGER NOT NULL, note_id INTEGER NOT NULL,
 note_gimmick_type INTEGER NOT NULL, skill_master_id INTEGER NOT NULL, name TEXT NOT NULL,
 PRIMARY KEY (live_difficulty_id, note_id));
CREATE TABLE m_live_note_wave_gimmick_group (live_difficulty_id INTEGER NOT NULL, wave_id INTEGER NOT NULL,
 state INTEGER NOT NULL, skill_id INTEGER NOT NULL, name TEXT NOT NULL, description TEXT NOT NULL,
 PRIMARY KEY (live_difficulty_id, wave_id, state, skill_id));
CREATE TABLE m_live_evaluation_drop (live_difficulty_master_id INTEGER NOT NULL, evaluation_type INTEGER NOT NULL,
 PRIMARY KEY (live_difficulty_master_id, evaluation_type));
CREATE TABLE m_live_difficulty_illust (live_difficulty_m_id INTEGER NOT NULL PRIMARY KEY, illust_asset_path TEXT NOT NULL);
CREATE TABLE m_live_difficulty_override_member_mapping (difficulty_id INTEGER NOT NULL, position INTEGER NOT NULL,
 member_master_id INTEGER, PRIMARY KEY (difficulty_id, position));
CREATE TABLE m_live_playable_setting (live_difficulty_id INTEGER NOT NULL PRIMARY KEY,
 live_playable_tutorial_pattern INTEGER NOT NULL);
"""


def catalog_script(platform, *, ios_timeline=True):
    suffix = "i" if platform == "i" else ""
    rows = [("A2101", f"tl2101{suffix}"), ("A2201", f"tl2201{suffix}")]
    if platform == "i" and not ios_timeline:
        rows = rows[1:]
    timeline_rows = ",".join(f"('{key}','{pack}',0,{TIMELINE_SIZE},4,7)" for key, pack in rows)
    mapping_rows = ",".join(f"('live:{key[1:]}','{pack}',{TIMELINE_SIZE},NULL,0,0)" for key, pack in rows)
    pack_rows = ",".join(f"('{pack}',0)" for _, pack in rows)
    return f"""
CREATE TABLE m_asset_package (package_key TEXT NOT NULL PRIMARY KEY, version TEXT NOT NULL, pack_num INTEGER NOT NULL);
CREATE TABLE m_asset_package_mapping (package_key TEXT NOT NULL, pack_name TEXT NOT NULL, file_size INTEGER NOT NULL,
 metapack_name TEXT NULL, metapack_offset INTEGER NOT NULL, category INTEGER NOT NULL, PRIMARY KEY (package_key, pack_name));
CREATE TABLE m_asset_pack (pack_name TEXT NOT NULL PRIMARY KEY, auto_delete INTEGER NOT NULL);
CREATE TABLE live_timeline (asset_path TEXT NOT NULL PRIMARY KEY, pack_name TEXT NOT NULL, head INTEGER NOT NULL,
 size INTEGER NOT NULL, key1 INTEGER NOT NULL, key2 INTEGER NOT NULL);
CREATE TABLE live_timeline_dependency (asset_path TEXT NOT NULL, dependency TEXT NOT NULL, PRIMARY KEY (asset_path, dependency));
CREATE TABLE texture (asset_path TEXT NOT NULL PRIMARY KEY, pack_name TEXT NOT NULL, head INTEGER NOT NULL,
 size INTEGER NOT NULL, key1 INTEGER NOT NULL, key2 INTEGER NOT NULL);
CREATE TABLE m_asset_sound (sheet_name TEXT NOT NULL PRIMARY KEY, acb_pack_name TEXT, awb_pack_name TEXT);
INSERT INTO m_asset_package VALUES ('main','main-v',3),('music:21','m21-v',2),('music:22','m22-v',1),
 ('live:2101','l2101-v',1),('live:2201','l2201-v',1);
INSERT INTO m_asset_package_mapping VALUES ('main','jk_pack',4000,NULL,0,8),('main','sabi21a',900,NULL,0,6),
 ('main','sabi21w',9000,NULL,0,6),('music:21','m21acb',1200,NULL,0,0),('music:21','m21awb',120000,NULL,0,0),
 ('music:22','m22acb',1300,NULL,0,0),{mapping_rows};
INSERT INTO m_asset_pack VALUES ('jk_pack',0),('sabi21a',0),('sabi21w',0),('m21acb',0),('m21awb',0),('m22acb',0),
 {pack_rows};
INSERT INTO live_timeline VALUES {timeline_rows};
INSERT INTO live_timeline_dependency VALUES ('A2101','dance01');
INSERT INTO texture VALUES ('jk21','jk_pack',100,2000,3,4),('jk22','jk_pack',2100,1000,3,4);
INSERT INTO m_asset_sound VALUES ('music_0021','m21acb','m21awb'),('music_0021_SABI','sabi21a','sabi21w'),
 ('music_0022','m22acb',NULL);
"""


USERDATA = """
CREATE TABLE u_status (user_id INTEGER PRIMARY KEY NOT NULL, last_live_difficulty_id INTEGER NULL,
 max_score_live_difficulty_master_id TEXT NULL, max_combo_live_difficulty_master_id TEXT NULL);
CREATE TABLE u_live_mv_deck (user_id INTEGER NOT NULL, live_master_id INTEGER NOT NULL, member_master_id_1 TEXT NULL,
 PRIMARY KEY (user_id, live_master_id));
INSERT INTO u_status VALUES (1,21301,'null','null');
"""


def stage_chart(difficulty_id):
    return {"live_difficulty_id": difficulty_id,
            "live_notes": [{"id": 1, "call_time": 500, "note_type": 1, "note_position": 2, "gimmick_id": 0,
                            "note_action": 1, "wave_id": 0, "note_random_drop_color": 99, "auto_judge_type": 20}],
            "live_wave_settings": [], "note_gimmicks": [], "stage_gimmick_dict": []}


@contextmanager
def connect(path):
    database = sqlite3.connect(path)
    try:
        yield database
        database.commit()
    finally:
        database.close()


def build_root(root, *, ios_timeline=True):
    """Synthetic GL game databases, stage files and userdata under ``root`` (no game data)."""
    root = Path(root)
    folder = root / "assets/db/gl"
    folder.mkdir(parents=True)
    with connect(folder / "masterdata.db") as database:
        database.executescript(MASTER)
    for language in ("en", "ko", "zh"):
        with connect(folder / f"dictionary_{language}_k.db") as database:
            database.executescript("CREATE TABLE m_dictionary (id TEXT NOT NULL PRIMARY KEY, message TEXT NOT NULL);"
                                   "INSERT INTO m_dictionary VALUES ('song_name_21','Base song'),"
                                   "('stage_name_101','Star stage'),('song_copyright_21','(c) base');")
        for platform in ("a", "i"):
            with connect(folder / f"asset_{platform}_{language}.db") as database:
                database.executescript(catalog_script(platform, ios_timeline=ios_timeline))
    stages = root / "assets/stages"
    stages.mkdir(parents=True)
    for difficulty in (21301, 22301):
        (stages / f"{difficulty}.json").write_text(json.dumps(stage_chart(difficulty)))
    with connect(root / "userdata.db") as database:
        database.executescript(USERDATA)
    (root / "static").mkdir()
    return root


# ---------------------------------------------------------------- synthetic native timelines

def base_tracks():
    return [
        {"id": "cab-1:10", "kind": "camera", "label": "CameraMotion/Camera1", "nativeClass": "AnimationTrack",
         "muted": False, "binding": "/EntryPoint/Live/Cameras/MainCamera",
         "events": [{"id": "cab-1:10:0", "start": 0.0, "duration": 2.0, "label": "cut1",
                     "values": {"clipIn": 0.0, "asset": "cab-1:11",
                                "keyframes": [{"time": 0.0, "position": [0, 1, -5], "rotation": [0, 0, 0, 1], "fov": 30},
                                              {"time": 2.0, "position": [0, 1, -4], "rotation": [0, 0, 0, 1], "fov": 30}]},
                     "editableValues": ["clipIn", "keyframes"]}]},
        {"id": "cab-1:20", "kind": "bloom", "label": "StageEffect/Bloom", "nativeClass": "LiveBloomTrack", "muted": False,
         "events": [{"id": "cab-1:20:0", "start": 1.0, "duration": 3.0, "label": "LiveBloomClip",
                     "values": {"clipIn": 0.0, "intensity": 1.0, "mixIn": [0, 1]},
                     "editableValues": ["clipIn", "intensity"]}]},
        {"id": "cab-1:30", "kind": "lighting", "label": "StageEffect/Ambient", "nativeClass": "LiveStageAmbientTrack",
         "muted": False, "events": [{"id": "cab-1:30:0", "start": 0.0, "duration": 4.0, "label": "Ambient",
                                     "values": {"clipIn": 0.0, "color": {"r": 1, "g": 1, "b": 1, "a": 1}},
                                     "editableValues": ["clipIn", "color"]}]},
    ]


def timeline_bytes(platform, tracks=None, *, size=TIMELINE_SIZE, tag="stock"):
    document = {"platform": platform, "tag": tag, "duration": 4.0, "tracks": tracks or base_tracks(), "warnings": []}
    data = b"UnityFS\0" + json.dumps(document, sort_keys=True).encode()
    if size is not None:
        assert len(data) <= size, len(data)
        data += b" " * (size - len(data))
    return data


def fake_parse(raw, name, **_options):
    document = json.loads(raw[8:].rstrip(b" ").decode())
    return {"duration": document["duration"], "tracks": document["tracks"], "warnings": document["warnings"]}


EXPORTS = []


def fake_export(raw, name, tracks):
    original = fake_parse(raw, name)
    EXPORTS.append({"base": json.loads(raw[8:].rstrip(b" ").decode()), "tracks": copy.deepcopy(tracks)})
    if original["tracks"] == tracks:
        return raw
    mv_studio_timeline._changes(original, {**original, "tracks": tracks})  # the exporter's own structure rules
    document = json.loads(raw[8:].rstrip(b" ").decode())
    document.update(tracks=tracks, tag="edited")
    return b"UnityFS\0" + json.dumps(document, sort_keys=True).encode()


def png_bytes(width, height, color=(200, 30, 60), mode="RGB", **save):
    from PIL import Image
    image = Image.new(mode, (width, height), color)
    for x in range(min(width, 37)):
        image.putpixel((x, x % height), (10, 200, 90) if mode == "RGB" else (10, 200, 90, 255))
    buffer = io.BytesIO()
    image.save(buffer, "PNG", **save)
    return buffer.getvalue()


def jpeg_bytes(width, height, exif=None):
    from PIL import Image
    image = Image.new("RGB", (width, height), (40, 80, 160))
    for x in range(width):
        image.putpixel((x, 0), (255, 255, 0))
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=92, **({"exif": exif} if exif else {}))
    return buffer.getvalue()


def wav_bytes(frames, *, rate=44100, channels=2, bits=16):
    import struct
    block = channels * bits // 8
    data = bytes(frames * block)
    return (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVEfmt " +
            struct.pack("<IHHIIHH", 16, 1, channels, rate, rate * block, block, bits) + b"data" +
            struct.pack("<I", len(data)) + data)


def opened_song(song):
    """source.registeredSong as a game import of the registered ``song`` records it (mv_studio_game)."""
    return {"revision": song["revision"], "updatedAt": song["updatedAt"], "templateLiveId": song["templateLiveId"]}


@contextmanager
def store_clock(seconds):
    """The Elichika store's update time (int(time.time()) in mv_studio_manage) fixed at ``seconds``."""
    with mock.patch.object(mv_studio_manage, "time", type("Clock", (), {"time": staticmethod(lambda: seconds)})):
        yield


class FakeJob:
    def __init__(self):
        self.events, self.cancel_event = [], threading.Event()

    def emit(self, event):
        self.events.append(event)

    def log(self, line):
        self.events.append({"type": "log", "line": line})

    def progress(self, done, total):
        self.events.append({"type": "progress", "done": done, "total": total})

    def should_stop(self):
        return self.cancel_event.is_set()

    def stages(self):
        return [event["stage"] for event in self.events if event["type"] == "mv-stage"]

    def song(self):
        return next((event for event in self.events if event["type"] == "mv-song"), None)


class Case(unittest.TestCase):
    """Synthetic root, a library folder, fake native timelines and pack loading."""

    ios_timeline = True

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="mv-register-test-")
        self.addCleanup(temporary.cleanup)
        self.temp = Path(temporary.name)
        self.root = build_root(self.temp / "root", ios_timeline=self.ios_timeline)
        self.library = self.temp / "library"
        (self.library / "modded").mkdir(parents=True)
        environment = mock.patch.dict(os.environ, {"SUKUSTA_DIR": str(self.library),
                                                    "SUKUSTA_BACKUP_ROOT": str(self.temp / "backups")})
        environment.start()
        self.addCleanup(environment.stop)
        register._PARSED.clear()
        EXPORTS.clear()
        self.local = {"tl2101": timeline_bytes("android"), "tl2101i": timeline_bytes("ios"),
                      "tl2201": timeline_bytes("android", tag="other"), "tl2201i": timeline_bytes("ios", tag="other")}
        self.remote = {}
        self.loads = []

        def load(repo_root, descriptor, *, download, deadline=None):
            name = descriptor["pack_name"]
            self.loads.append((name, download))
            if name in self.local:
                return self.local[name]
            if download and name in self.remote:
                return self.remote[name]
            published = self.root / "static" / name
            if name.startswith("mvstudio_") and mv_studio_live is not None and published.is_file():
                # A pack the store published (a registered song's timeline); its keystream is self-inverse.
                return native.encrypt_bytes(published.read_bytes())[descriptor["head"]:
                                                                    descriptor["head"] + descriptor["size"]]
            return None

        for target, name, value in ((register, "_load", load),
                                    (mv_studio_timeline, "parse_timeline", fake_parse),
                                    (mv_studio_timeline, "export_timeline", fake_export),
                                    (register, "_blob_platform", lambda raw: json.loads(raw[8:].rstrip(b" "))["platform"])):
            patcher = mock.patch.object(target, name, side_effect=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.server_sessions = []

        @contextmanager
        def session(job, *, stop, restart):
            state = type("Session", (), {"was_running": True, "restarted": restart, "restart_pending": False})()
            self.server_sessions.append({"stop": stop, "restart": restart, "exports": len(EXPORTS)})
            job.emit({"type": "test-server-stop"})
            yield state
            job.emit({"type": "test-server-start"})

        patcher = mock.patch.object(register, "_server_session", side_effect=session)
        patcher.start()
        self.addCleanup(patcher.stop)
        if mv_studio_live is not None:
            self.validated = []

            def stock(repo_root, row, physical, deadline):
                return self.local.get(row["pack_name"])

            def validate(raw, original, platform, deadline):
                self.validated.append((json.loads(raw[8:].rstrip(b" "))["platform"],
                                       json.loads(original[8:].rstrip(b" "))["platform"], platform))

            for target, name, value in ((native, "_stock_timeline", stock), (native, "_validate_timeline", validate),
                                        (costume_management, "assert_server_stopped", lambda: None)):
                patcher = mock.patch.object(target, name, side_effect=value)
                patcher.start()
                self.addCleanup(patcher.stop)
            patcher = mock.patch.object(register, "_lifecycle", return_value=None)
            patcher.start()
            self.addCleanup(patcher.stop)

    def project(self, *, platform="android", tracks=None, source=None, native_bytes=None, **fields):
        project = mv_studio._blank("내 MV", source or {"kind": "game", "region": "gl", "platform": platform,
                                                     "liveId": 21, "assetId": 2101, "mvOnly": False,
                                                     "registered": False})
        project["tracks"] = copy.deepcopy(tracks if tracks is not None else base_tracks())
        project["duration"] = 4.0
        project.update(fields)
        raw = native_bytes if native_bytes is not None else self.local["tl2101" + ("i" if platform == "ios" else "")]
        return mv_studio._register(project, raw)

    def edited(self, project, *, keyframe=True, bloom=True, timing=False):
        tracks = project["tracks"]
        if keyframe:
            tracks[0]["events"][0]["values"]["keyframes"][1]["position"] = [0, 1.5, -3]
        if bloom:
            tracks[1]["events"][0]["values"]["intensity"] = 2.5
        if timing:
            tracks[2]["events"][0]["start"] = 0.5
        return project

    def request(self, project, **overrides):
        data = {"mode": "new", "project": project, "title": "내 MV", "jacket": {"kind": "base"},
                "audio": {"kind": "base"}, "platforms": ["android", "ios"], "download": False}
        data.update(overrides)
        return register.validate_register(self.root, data)

    def run_job(self, request, *, managed=False):
        job = FakeJob()
        with mock.patch.object(register, "managed", return_value=managed):
            summary = register.run_register(job, self.root, request)
        return job, summary

    def jacket_file(self, name, data):
        path = self.library / "modded" / name
        path.write_bytes(data)
        return str(path)


# ---------------------------------------------------------------- pure helpers

class NormalizeTests(unittest.TestCase):
    def test_restores_track_settings_and_preview_values_and_counts_edits(self):
        original = base_tracks()
        # Directly in a quality category, so the game's quality settings decide its mute.
        original[1]["label"] = "StageEffect/Expert/Post/Bloom"
        tracks = copy.deepcopy(original)
        tracks[1]["muted"] = True
        tracks[1]["editorHidden"] = True
        tracks[0]["shaftSlot"] = 3
        tracks[1]["events"][0]["values"]["mixIn"] = [0, 0.5]
        tracks[1]["events"][0]["values"]["intensity"] = 3.0
        tracks[1]["events"][0]["values"]["previewOnlyExtra"] = 1
        tracks[2]["events"][0]["start"] = 0.25
        tracks[2]["events"][0]["editableValues"] = ["clipIn"]
        tracks[0]["events"][0]["values"]["keyframes"][0]["fov"] = 40
        normalized, report = register.normalize(original, tracks)
        self.assertEqual(report, {"trackSettings": ["StageEffect/Expert/Post/Bloom"],
                                  "previewValues": ["StageEffect/Expert/Post/Bloom"]})
        self.assertFalse(normalized[1]["muted"])
        self.assertNotIn("editorHidden", normalized[1])
        self.assertNotIn("shaftSlot", normalized[0])
        self.assertEqual(normalized[1]["events"][0]["values"]["mixIn"], [0, 1])
        self.assertNotIn("previewOnlyExtra", normalized[1]["events"][0]["values"])
        self.assertEqual(normalized[1]["events"][0]["values"]["intensity"], 3.0)
        self.assertEqual(normalized[2]["events"][0]["editableValues"], ["clipIn", "color"])
        self.assertEqual(register.count_edits(original, normalized),
                         {"cameraShots": 1, "values": 1, "timing": 1, "clips": 3, "tracks": 0})
        # The exporter accepts the result as it is.
        mv_studio_timeline._changes({"duration": 4.0, "tracks": original, "warnings": []},
                                    {"duration": 4.0, "tracks": normalized, "warnings": []})

    def test_exportable_track_fields_stay(self):
        original = base_tracks()
        tracks = copy.deepcopy(original)
        tracks[1]["muted"] = True
        normalized, report = register.normalize(original, tracks)
        self.assertTrue(normalized[1]["muted"])
        self.assertEqual(report["trackSettings"], [])
        self.assertEqual(register.count_edits(original, normalized)["tracks"], 1)
        self.assertTrue(register.has_edits(register.count_edits(original, normalized)))

    def test_structure_changes_are_refused_with_track_labels(self):
        original = base_tracks()
        removed = copy.deepcopy(original)
        removed[1]["events"] = []
        with self.assertRaises(register.StructureError) as caught:
            register.normalize(original, removed)
        self.assertEqual(caught.exception.labels, ["StageEffect/Bloom"])
        self.assertEqual(str(caught.exception), register.STRUCTURE)
        added = copy.deepcopy(original) + [{"id": "new", "label": "Added track", "events": []}]
        with self.assertRaises(register.StructureError) as caught:
            register.normalize(original, added)
        self.assertEqual(caught.exception.labels, ["Added track"])
        reordered = [original[1], original[0], original[2]]
        with self.assertRaises(register.StructureError) as caught:
            register.normalize(original, reordered)
        self.assertEqual(caught.exception.labels, ["CameraMotion/Camera1", "StageEffect/Bloom"])

    def test_fingerprint_is_stable_and_follows_exportable_content_only(self):
        tracks = base_tracks()
        tracks[1]["label"] = "StageEffect/Expert/Post/Bloom"  # Its mute does not reach the game.
        first = register.timeline_fingerprint("android", "tl:0:4096:4:7", tracks)
        self.assertEqual(first, register.timeline_fingerprint("android", "tl:0:4096:4:7", copy.deepcopy(tracks)))
        noisy = copy.deepcopy(tracks)
        noisy[1]["muted"] = True
        noisy[1]["events"][0]["values"]["mixIn"] = [5]
        self.assertEqual(first, register.timeline_fingerprint("android", "tl:0:4096:4:7", noisy))
        edited = copy.deepcopy(tracks)
        edited[1]["events"][0]["values"]["intensity"] = 2.0
        self.assertNotEqual(first, register.timeline_fingerprint("android", "tl:0:4096:4:7", edited))
        self.assertNotEqual(first, register.timeline_fingerprint("ios", "tl:0:4096:4:7", tracks))
        self.assertNotEqual(first, register.timeline_fingerprint("android", "other:0:4096:4:7", tracks))
        self.assertLessEqual(len(first), 128)

    def test_only_values_the_fingerprint_covers_are_baked(self):
        """A clip whose saved editableValues lack a base-editable key (an older project) does not bake
        that key, so a later update that changes only it cannot be skipped by an equal fingerprint."""
        original = base_tracks()
        stale = copy.deepcopy(original)
        stale[1]["events"][0]["editableValues"] = ["clipIn"]
        stale[1]["events"][0]["values"]["intensity"] = 2.5
        normalized, report = register.normalize(original, stale)
        self.assertEqual(normalized[1]["events"][0]["values"]["intensity"], 1.0)
        self.assertEqual(normalized[1]["events"][0]["editableValues"], ["clipIn", "intensity"])
        self.assertEqual(report["previewValues"], ["StageEffect/Bloom"])
        self.assertEqual(register.count_edits(original, normalized)["clips"], 0)
        identity = "tl:0:4096:4:7"
        unedited = copy.deepcopy(stale)
        unedited[1]["events"][0]["values"]["intensity"] = 1.0
        self.assertEqual(register.timeline_fingerprint("android", identity, stale),
                         register.timeline_fingerprint("android", identity, unedited),
                         "A value that is not baked does not change the fingerprint")
        # Every baked value is fingerprinted: two projects that bake differently never share a fingerprint.
        for key, value in (("clipIn", 0.5), ("intensity", 2.0)):
            edited = copy.deepcopy(original)
            edited[1]["events"][0]["values"][key] = value
            baked, _ = register.normalize(original, edited)
            self.assertEqual(baked[1]["events"][0]["values"][key], value)
            self.assertNotEqual(register.timeline_fingerprint("android", identity, edited),
                                register.timeline_fingerprint("android", identity, original))

    def test_songs_registered_before_track_mutes_rebake(self):
        # Track mutes changed what a bake writes: a song registered under an older version rebakes on
        # its next update instead of keeping its timeline by fingerprint.
        self.assertNotIn(register.FINGERPRINT_VERSION, ("mv-studio-register-1", "mv-studio-register-2"))

    def test_exportable_track_fields_are_fingerprinted(self):
        original = base_tracks()
        muted = copy.deepcopy(original)
        muted[1]["muted"] = True
        identity = "tl:0:4096:4:7"
        plain = register.timeline_fingerprint("android", identity, original)
        self.assertNotEqual(plain, register.timeline_fingerprint("android", identity, muted))
        # A mute that does not reach the game (a group, a quality category's track) is not fingerprinted.
        for label, native in (("StageEffect/Expert/Post/Bloom", "LiveBloomTrack"), ("StageEffect/Bloom", "GroupTrack")):
            relabelled, quiet = copy.deepcopy(original), copy.deepcopy(muted)
            for tracks in (relabelled, quiet):
                tracks[1].update(label=label, nativeClass=native)
            self.assertEqual(register.timeline_fingerprint("android", identity, relabelled),
                             register.timeline_fingerprint("android", identity, quiet), label)

    def test_shift_beat_moves_the_first_beat_by_the_offset(self):
        beat = {"bpm": 120.0, "startSample": 44100, "endSample": 441000}
        self.assertEqual(register.shift_beat(beat, 0.25), {"bpm": 120.0, "firstBeat": 0.75})
        # A beat grid that starts before the trimmed audio moves to its next beat.
        self.assertEqual(register.shift_beat(beat, 1.2), {"bpm": 120.0, "firstBeat": 0.3})
        segments = {"segments": [{"bpm": 120.0, "startSample": 0, "endSample": 44099},
                                 {"bpm": 90.0, "startSample": 44100, "endSample": 441000}]}
        shifted = register.shift_beat(segments, 0.5)
        self.assertEqual(shifted["segments"], [{"bpm": 120.0, "startSample": 0}, {"bpm": 90.0, "startSample": 22050}])
        self.assertIsNone(register.shift_beat({"bpm": "x"}, 0))


class SourceSongTests(unittest.TestCase):
    """register._same_song: is the song now under a project's source ID the one it was opened from?"""

    def test_updates_keep_the_song_and_a_later_song_under_the_id_is_another(self):
        opened = {"revision": 2, "updatedAt": 1000, "templateLiveId": 21}
        song = lambda revision, updated, template=21: {"revision": revision, "updatedAt": updated,  # noqa: E731
                                                       "templateLiveId": template}
        for current, expected in ((song(2, 1000), True), (song(3, 1060), True), (song(9, 1000), True),
                                  (song(2, 1060), False), (song(1, 1060), False), (song(1, 1000), False),
                                  (song(3, 1060, template=22), False), (song(2, 1000, template=22), False)):
            with self.subTest(current=current):
                self.assertIs(register._same_song(opened, current), expected)
        # Rows from before the store's revisions: revision 0 and no update time.
        self.assertTrue(register._same_song({"revision": 0, "updatedAt": None, "templateLiveId": 21},
                                            {"revision": 0, "updatedAt": None, "templateLiveId": 21}))
        self.assertTrue(register._same_song({"revision": 0, "updatedAt": None, "templateLiveId": 21}, song(1, 1060)))
        # Projects opened before the song was recorded, or with a damaged record, follow the ID.
        for opened in (None, "song", {}, {"revision": "2", "updatedAt": 1000, "templateLiveId": 21},
                       {"revision": 2, "updatedAt": 1000.5, "templateLiveId": 21},
                       {"revision": 2, "updatedAt": 1000, "templateLiveId": 0}, {"revision": -1, "templateLiveId": 21}):
            with self.subTest(opened=opened):
                self.assertTrue(register._same_song(opened, song(1, 2000, template=22)))


class JacketTests(Case):
    def test_exact_400_png_and_jpeg_are_stored_byte_for_byte(self):
        for name, data in (("a.png", png_bytes(400, 400)), ("b.jpg", jpeg_bytes(400, 400))):
            path = self.jacket_file(name, data)
            self.assertEqual(register.prepare_jacket(path), data)
            self.assertEqual(register.prepare_jacket(path, {"x": 0, "y": 0, "size": 400}), data)
            preview = register.jacket_preview(path)
            self.assertEqual((preview["width"], preview["height"], preview["exact"]), (400, 400, True))
            self.assertTrue(preview["previewUrl"].startswith("data:image/png;base64,"))

    def test_other_squares_are_resized_once_and_non_squares_need_a_crop(self):
        from PIL import Image
        square = self.jacket_file("square.png", png_bytes(512, 512))
        result = register.prepare_jacket(square)
        with Image.open(io.BytesIO(result)) as image:
            self.assertEqual((image.format, image.size), ("PNG", (400, 400)))
        wide = self.jacket_file("wide.png", png_bytes(900, 500))
        with self.assertRaisesRegex(ValueError, "Choose the square area for the jacket."):
            register.prepare_jacket(wide)
        for crop in ({"x": 600, "y": 0, "size": 400}, {"x": 0, "y": 0, "size": 0}, {"x": 0, "y": 0},
                     {"x": 0.5, "y": 0, "size": 400}):
            with self.assertRaisesRegex(ValueError, "The jacket area must be a square inside the image."):
                register.prepare_jacket(wide, crop)
        preview = register.jacket_preview(wide)
        self.assertEqual((preview["width"], preview["height"], preview["square"]), (900, 500, False))

    def test_a_400_crop_keeps_exact_pixels_and_a_larger_crop_is_resized(self):
        from PIL import Image
        source = png_bytes(900, 500)
        wide = self.jacket_file("wide.png", source)
        cut = register.prepare_jacket(wide, {"x": 13, "y": 50, "size": 400})
        with Image.open(io.BytesIO(source)) as original, Image.open(io.BytesIO(cut)) as image:
            self.assertEqual(image.size, (400, 400))
            self.assertEqual(image.tobytes(), original.crop((13, 50, 413, 450)).tobytes())
        bigger = register.prepare_jacket(wide, {"x": 0, "y": 0, "size": 500})
        with Image.open(io.BytesIO(bigger)) as image:
            self.assertEqual(image.size, (400, 400))

    def test_exif_orientation_is_applied_before_cropping(self):
        from PIL import Image
        exif = Image.Exif()
        exif[0x0112] = 6  # Rotate 90 degrees clockwise on display.
        path = self.jacket_file("rotated.jpg", jpeg_bytes(400, 300, exif.tobytes()))
        preview = register.jacket_preview(path)
        self.assertEqual((preview["width"], preview["height"]), (300, 400))
        result = register.prepare_jacket(path, {"x": 0, "y": 50, "size": 300})
        with Image.open(io.BytesIO(result)) as image:
            self.assertEqual((image.format, image.size), ("PNG", (400, 400)))

    def test_paths_outside_the_library_are_refused(self):
        outside = self.temp / "outside.png"
        outside.write_bytes(png_bytes(400, 400))
        with self.assertRaises(PermissionError):
            register.jacket_preview(str(outside))


class PcmTests(Case):
    def test_page_pcm_is_kept_in_the_media_cache(self):
        data = wav_bytes(44100)
        stored = register.store_pcm(data)
        self.assertEqual(stored["duration"], 1.0)
        path, kind = mv_studio.media(stored["name"])
        self.assertEqual((path.read_bytes(), kind), (data, "audio/wav"))
        pcm, digest = register._read_pcm(stored["name"])
        self.assertEqual(pcm.shape, (44100, 2))

    def test_malformed_or_wrong_format_wav_is_refused(self):
        for data in (b"RIFF0000WAVEjunk", wav_bytes(100, rate=48000), wav_bytes(100, channels=1), wav_bytes(100, bits=8)):
            with self.assertRaises(ValueError):
                register.store_pcm(data)
        with self.assertRaisesRegex(ValueError, "The converted audio is empty"):
            register.store_pcm(b"")
        with self.assertRaisesRegex(ValueError, "no longer available"):
            register._read_pcm("0" * 32 + ".wav")


# ---------------------------------------------------------------- plan

@NEEDS_STORE
class PlanTests(Case):
    def plan(self, project, **options):
        return register.plan(self.root, project, **options)

    def test_game_project_without_edits(self):
        result = self.plan(self.project())
        self.assertEqual(result["base"], {"liveId": 21, "assetId": 2101, "title": "Base song", "stage": "Star stage",
                                          "fixed": True, "registered": False})
        self.assertEqual((result["region"], result["target"], result["title"]), ("gl", "new", "내 MV"))
        self.assertEqual(result["platforms"], {"android": {"status": "project"}, "ios": {"status": "local"}})
        self.assertTrue(result["timeline"]["unchanged"])
        self.assertEqual(result["timeline"]["bake"], [])
        self.assertEqual(result["blocked"], [])
        self.assertEqual(result["audio"]["default"], "base")
        self.assertEqual(result["jacket"]["default"], "base")
        self.assertEqual(EXPORTS, [], "The plan never bakes")

    def test_counts_edits_and_lists_what_does_not_reach_the_game(self):
        project = self.edited(self.project(), timing=True)
        project["tracks"][1]["editorHidden"] = True
        project["tracks"][1]["events"][0]["values"]["mixIn"] = [0, 0.2]
        project["assets"] = [{"id": "0123456789abcdef", "kind": "stage", "label": "stage.glb", "path": "stage.glb",
                              "status": "loaded"}]
        project["performers"] = [{"id": "member-1", "position": 1, "motion": {"clips": []}, "suitSource": "pinned",
                                  "transform": {"position": [1, 0, 0]}}]
        project["quality"] = {"modes": [{"id": 1, "values": {"shadow": True}}], "options": [], "mode": 1,
                              "values": {"shadow": False}}
        project["editor"] = {"version": 1, "originals": {}, "camera": {"version": 1, "shots": {}, "rigs": [{"id": "r"}]}}
        result = self.plan(project, unbaked=[{"kind": "camera", "eventId": "cab-1:10:0", "reason": "pending"}])
        self.assertEqual(result["edits"], {"cameraShots": 1, "values": 1, "timing": 1, "clips": 3, "tracks": 0,
                                           "follow": True})
        self.assertFalse(result["timeline"]["unchanged"])
        self.assertEqual(result["timeline"]["bake"], ["android", "ios"])
        self.assertEqual([note["message"] for note in result["notInGame"]],
                         [register.NOT_TRACK_SETTINGS, register.NOT_VALUES, register.NOT_STAGE, register.NOT_POSITIONS,
                          register.NOT_COSTUMES, register.NOT_QUALITY, register.NOT_UNBAKED])
        self.assertEqual(result["notInGame"][0]["labels"], ["StageEffect/Bloom"])
        self.assertIn({"message": register.UNBAKED}, result["blocked"])
        self.assertIn({"message": register.FOLLOW_NOTE}, result["warnings"])

    def test_a_mute_only_project_is_an_edit(self):
        # Only a track mute that reaches the game (no clip edit): the original MV must not play.
        project = self.project()
        project["tracks"][0]["muted"] = True
        result = self.plan(project)
        self.assertEqual(result["edits"], {"cameraShots": 0, "values": 0, "timing": 0, "clips": 0, "tracks": 1,
                                           "follow": False})
        self.assertFalse(result["timeline"]["unchanged"])
        self.assertEqual(result["timeline"]["bake"], ["android", "ios"])
        self.assertEqual(result["notInGame"], [])
        stock = {"kind": "stock", "raw": self.local["tl2101"]}
        self.assertFalse(register._unchanged_stock(stock, project["tracks"]))
        self.assertTrue(register._unchanged_stock(stock, base_tracks()))
        self.assertEqual(EXPORTS, [], "The plan never bakes")

    def test_structural_change_blocks_with_the_track_label(self):
        project = self.project()
        project["tracks"][2]["events"].append({"id": "cab-1:30:1", "start": 3, "duration": 1, "label": "x",
                                               "values": {}, "editableValues": []})
        result = self.plan(project)
        self.assertEqual(result["blocked"], [{"message": register.STRUCTURE, "labels": ["StageEffect/Ambient"]}])

    def test_originals_per_platform_local_download_missing(self):
        del self.local["tl2101i"]
        self.remote["tl2101i"] = timeline_bytes("ios")
        result = self.plan(self.edited(self.project()))
        self.assertEqual(result["platforms"]["ios"], {"status": "download", "bytes": TIMELINE_SIZE})
        self.assertEqual(result["timeline"]["download"], ["ios"])
        self.assertNotIn(("tl2101i", True), self.loads, "The plan never downloads")
        ios = self.project(platform="ios", native_bytes=timeline_bytes("ios"))
        del self.local["tl2101"]
        result = self.plan(ios)
        self.assertEqual(result["platforms"], {"android": {"status": "download", "bytes": TIMELINE_SIZE},
                                               "ios": {"status": "project"}})

    def test_mod_project_needs_a_chosen_base(self):
        mod = self.project(source={"kind": "mod"}, native_bytes=timeline_bytes("ios", tag="mod"))
        result = self.plan(mod)
        self.assertEqual(result["blocked"], [{"message": register.CHOOSE_BASE}])
        self.assertIsNone(result["base"])
        chosen = self.plan(self.edited(mod), template={"region": "gl", "liveId": 21, "assetId": 2101})
        self.assertEqual(chosen["base"]["fixed"], False)
        self.assertEqual(chosen["projectPlatform"], "ios")
        self.assertEqual(chosen["timeline"]["kind"], "mod")
        self.assertEqual(chosen["platforms"]["ios"], {"status": "local"})
        other = self.project(source={"kind": "mod"}, native_bytes=timeline_bytes(
            "ios", [{**base_tracks()[0], "id": "cab-9:10"}], tag="mod"))
        refused = self.plan(other, template={"region": "gl", "liveId": 21, "assetId": 2101})
        self.assertEqual(refused["blocked"], [{"message": register.MOD_MISMATCH}])

    def test_from_scratch_project_registers_the_base_timeline_unchanged(self):
        project = mv_studio._register(mv_studio._blank("Scratch"), None)
        project["soundtrack"] = {"url": "/api/mv-studio/media/" + "a" * 32 + ".mp3", "offset": 0, "duration": 30}
        with mock.patch.object(register, "encoder_available", return_value=True):
            result = self.plan(project, template={"region": "gl", "liveId": 21, "assetId": 2101})
        self.assertEqual(result["timeline"]["kind"], None)
        self.assertEqual(result["timeline"]["bake"], [])
        self.assertEqual(result["audio"]["default"], "project")
        self.assertEqual(result["audio"]["soundtrack"]["origin"], "project")

    def test_a_measured_soundtrack_length_fills_the_preview_start_and_warning(self):
        project = self.project()
        # mp3/ogg/m4a/flac imports record no duration; the page measures it and sends it with the plan.
        project["soundtrack"] = {"url": "/api/mv-studio/media/" + "c" * 32 + ".mp3", "offset": 0}
        unknown = self.plan(project)
        self.assertIsNone(unknown["audio"]["soundtrack"]["duration"])
        self.assertIsNone(unknown["audio"]["previewStart"])
        self.assertFalse([item for item in unknown["warnings"]
                          if item["message"] in (register.AUDIO_LONGER, register.AUDIO_SHORTER)])
        measured = self.plan(project, soundtrack_duration=34.5)
        self.assertEqual(measured["audio"]["soundtrack"]["duration"], 34.5)
        self.assertEqual(measured["audio"]["previewStart"], 14.5)
        self.assertIn({"message": register.AUDIO_LONGER, "values": {"seconds": 30.5}}, measured["warnings"])
        # A WAV import's own duration wins over the page's measurement.
        project["soundtrack"]["duration"] = 4.0
        self.assertEqual(self.plan(project, soundtrack_duration=34.5)["audio"]["soundtrack"]["duration"], 4.0)
        for bad in (0, -1, float("nan"), "30", True, 10 ** 9):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "request is invalid"):
                self.plan(project, soundtrack_duration=bad)

    def test_audio_defaults_and_offset_beat(self):
        project = self.project()
        project["soundtrack"] = {"url": "/api/mv-studio/media/" + "b" * 32 + ".wav", "offset": 0, "duration": 4.0,
                                 "origin": "game"}
        project["stage"] = {"beatSync": {"bpm": 120.0, "startSample": 22050, "endSample": 176400}}
        self.assertEqual(self.plan(project)["audio"]["default"], "base")
        project["soundtrack"]["offset"] = 0.25
        with mock.patch.object(register, "encoder_available", return_value=False):
            without = self.plan(project)
        self.assertEqual((without["audio"]["default"], without["encoder"]), ("base", False))
        self.assertIn({"message": register.OFFSET_BASE}, without["warnings"])
        with mock.patch.object(register, "encoder_available", return_value=True):
            result = self.plan(project)
        self.assertEqual(result["audio"]["default"], "project")
        self.assertEqual(result["audio"]["beat"], {"bpm": 120.0, "firstBeat": 0.25})
        project["soundtrack"].update(offset=0, duration=20.0)
        longer = self.plan(project)
        self.assertIn({"message": register.AUDIO_LONGER, "values": {"seconds": 16.0}}, longer["warnings"])


# ---------------------------------------------------------------- jobs against the real store

@NEEDS_STORE
class RegisterJobTests(Case):
    def songs(self):
        return mv_studio_live.list_mv_songs(self.root, region="gl")

    def test_new_registration_bakes_both_platforms_from_their_own_stock(self):
        project = self.edited(self.project(), timing=True)
        job, summary = self.run_job(self.request(project, credit="작곡 테스트"))
        song = job.song()["song"]
        self.assertEqual(summary, register.REGISTERED.replace("{title}", "내 MV").replace("{id}", str(song["liveId"])))
        self.assertEqual(song["platforms"], {"android": "custom", "ios": "custom"})
        self.assertEqual((song["title"], song["credit"], song["visible"]), ("내 MV", "작곡 테스트", True))
        self.assertEqual(sorted(song["fingerprints"]), ["android", "ios"])
        self.assertEqual([export["base"]["platform"] for export in EXPORTS], ["android", "ios"])
        self.assertEqual(EXPORTS[0]["tracks"], EXPORTS[1]["tracks"], "Both platforms receive the same tracks")
        self.assertEqual(sorted(self.validated), [("android", "android", 13), ("ios", "ios", 9)])
        self.assertEqual(job.stages(), ["check", "android", "ios", "write"])
        self.assertEqual(self.server_sessions, [], "A standalone register writes while the server runs")
        self.assertEqual(job.song()["restart"], "manual")
        self.assertEqual(len(self.songs()), 1)

    def test_unchanged_timeline_registers_the_stock_rows(self):
        job, _ = self.run_job(self.request(self.project()))
        song = job.song()["song"]
        self.assertEqual(song["platforms"], {"android": "stock", "ios": "stock"})
        self.assertEqual(song["fingerprints"], {})
        self.assertEqual(self.validated, [])

    def test_a_mute_only_project_bakes_both_platforms(self):
        project = self.project()
        project["tracks"][0]["muted"] = True
        job, _ = self.run_job(self.request(project))
        song = job.song()["song"]
        self.assertEqual(song["platforms"], {"android": "custom", "ios": "custom"})
        self.assertEqual(sorted(song["fingerprints"]), ["android", "ios"])
        self.assertEqual([export["base"]["platform"] for export in EXPORTS], ["android", "ios"])
        for export in EXPORTS:
            self.assertEqual([track["muted"] for track in export["tracks"]], [True, False, False])
        self.assertEqual(sorted(self.validated), [("android", "android", 13), ("ios", "ios", 9)])

    def test_one_unchanged_platform_gets_no_override(self):
        project = self.edited(self.project())
        # iOS stock already holds the edit: its export returns the stock bytes.
        self.local["tl2101i"] = timeline_bytes("ios", copy.deepcopy(project["tracks"]))
        job, _ = self.run_job(self.request(project))
        self.assertEqual(job.song()["song"]["platforms"], {"android": "custom", "ios": "stock"})

    def test_update_without_changes_writes_nothing_and_skips_the_bake(self):
        project = self.edited(self.project())
        jacket = self.jacket_file("j.png", png_bytes(400, 400))
        first, _ = self.run_job(self.request(project, jacket={"kind": "file", "path": jacket}), managed=True)
        live_id = first.song()["song"]["liveId"]
        self.assertEqual(first.stages(), ["check", "android", "ios", "jacket", "stop", "write", "restart"])
        self.assertEqual(self.server_sessions[0], {"stop": True, "restart": True, "exports": 2},
                         "Bakes run before the server stops")
        EXPORTS.clear()
        registered = self.project(source={"kind": "game", "region": "gl", "platform": "android", "liveId": live_id,
                                          "assetId": live_id * 100 + 1, "registered": True},
                                  tracks=project["tracks"], native_bytes=timeline_bytes("android", tag="custom"))
        plan = register.plan(self.root, registered)
        self.assertEqual((plan["target"], plan["audio"]["default"], plan["jacket"]["default"]), (live_id, "keep", "keep"))
        self.assertEqual(plan["timeline"]["keep"], ["android", "ios"])
        second, summary = self.run_job(self.request(registered, mode="update", liveId=live_id,
                                                    jacket={"kind": "file", "path": jacket}, audio={"kind": "keep"}),
                                       managed=True)
        self.assertEqual(summary, register.NO_CHANGES)
        self.assertEqual(EXPORTS, [])
        self.assertEqual(len(self.server_sessions), 1, "A no-op update does not stop the server")
        self.assertEqual((second.song()["changed"], second.song()["restart"]), (False, "none"))

    @staticmethod
    def panel_platforms(plan, *, download=False):
        """platformsFor(plan).send of mv-studio-register.js: every catalogued platform, minus the
        bakes whose original needs a download the user did not allow (after consent)."""
        timeline = plan["timeline"]
        skipped = [] if download else [platform for platform in timeline["download"] if platform in timeline["bake"]]
        return [platform for platform in register.PLATFORMS
                if plan["platforms"].get(platform, {}).get("status", "missing") != "missing" and platform not in skipped]

    def test_update_with_the_panel_payload_keeps_custom_timelines(self):
        """A no-op, title-only or jacket-only update of a song with custom timelines keeps them."""
        project = self.edited(self.project())
        first, _ = self.run_job(self.request(project), managed=True)
        live_id = first.song()["song"]["liveId"]
        self.assertEqual(first.song()["song"]["platforms"], {"android": "custom", "ios": "custom"})
        linked = dict(project, registration={"region": "gl", "liveId": live_id})
        plan = register.plan(self.root, linked)
        self.assertEqual((plan["target"], plan["timeline"]["keep"], plan["timeline"]["bake"]),
                         (live_id, ["android", "ios"], []))
        platforms = self.panel_platforms(plan)
        self.assertEqual(platforms, ["android", "ios"], "Kept platforms are sent")
        EXPORTS.clear()
        sessions = len(self.server_sessions)
        update = {"mode": "update", "liveId": live_id, "jacket": {"kind": "keep"}, "audio": {"kind": "keep"},
                  "platforms": platforms}
        job, summary = self.run_job(self.request(linked, **update), managed=True)
        self.assertEqual(summary, register.NO_CHANGES)
        self.assertEqual((job.song()["changed"], job.song()["restart"]), (False, "none"))
        self.assertEqual(len(self.server_sessions), sessions, "A no-op update does not stop the server")
        job, summary = self.run_job(self.request(linked, **update, title="새 제목"), managed=True)
        self.assertEqual(job.song()["parts"], ["title"])
        jacket = {"kind": "file", "path": self.jacket_file("j.png", png_bytes(400, 400))}
        job, _ = self.run_job(self.request(linked, **{**update, "jacket": jacket}, title="새 제목"), managed=True)
        self.assertEqual(job.song()["parts"], ["jacket"])
        song = mv_studio_live.describe_mv_song(self.root, region="gl", live_id=live_id)
        self.assertEqual((song["platforms"], song["title"]), ({"android": "custom", "ios": "custom"}, "새 제목"))
        self.assertEqual(EXPORTS, [], "Kept platforms are neither read nor baked")
        # A kept platform stays even when a client leaves it out: it needs no original and no bake.
        job, summary = self.run_job(self.request(linked, **{**update, "platforms": []}, title="새 제목"))
        self.assertEqual(summary, register.NO_CHANGES)
        self.assertEqual(mv_studio_live.describe_mv_song(self.root, region="gl", live_id=live_id)["platforms"],
                         {"android": "custom", "ios": "custom"})

    def reopened(self, live_id, platform="android"):
        """The project that 'Open' in the songs list makes: the song's own registered timeline, parsed."""
        song = mv_studio_live.describe_mv_song(self.root, region="gl", live_id=live_id)
        raw = register._registered_timelines(self.root, song)[platform]
        source = {"kind": "game", "region": "gl", "platform": platform, "liveId": live_id, "assetId": song["assetId"],
                  "mvOnly": True, "registered": True, "registeredSong": opened_song(song)}
        return self.project(platform=platform, source=source, tracks=fake_parse(raw, "reopen")["tracks"],
                            native_bytes=raw)

    @staticmethod
    def float32_export(raw, name, tracks):
        """The native writer stores 32-bit floats: a value read back is the float32 nearest the one written."""
        def f32(value):
            if type(value) is float:
                return struct.unpack("<f", struct.pack("<f", value))[0]
            if isinstance(value, list):
                return [f32(item) for item in value]
            if isinstance(value, dict):
                return {key: f32(item) for key, item in value.items()}
            return value
        return fake_export(raw, name, f32(tracks))

    def test_an_update_after_opening_the_song_keeps_it_without_a_bake_or_a_server_stop(self):
        """Opening a registered song reads its values back as the float32 the game stores
        (0.7 -> 0.699999988...), so the fingerprint of the posted project differs, yet nothing changed."""
        stored = struct.unpack("<f", struct.pack("<f", 0.7))[0]
        with mock.patch.object(register, "_export", side_effect=self.float32_export):
            project = self.project()
            project["tracks"][1]["events"][0]["values"]["intensity"] = 0.7
            project["tracks"][2]["events"][0]["values"]["color"]["r"] = 0.1
            first, _ = self.run_job(self.request(project), managed=True)
            song = first.song()["song"]
            live_id, sessions = song["liveId"], len(self.server_sessions)
            self.assertEqual(song["platforms"], {"android": "custom", "ios": "custom"})
            reopened = self.reopened(live_id)
            self.assertEqual(reopened["tracks"][1]["events"][0]["values"]["intensity"], stored)
            plan = register.plan(self.root, reopened)
            self.assertNotEqual(plan["timeline"]["fingerprints"], song["fingerprints"])
            self.assertEqual((plan["target"], plan["timeline"]["keep"], plan["timeline"]["bake"]),
                             (live_id, ["android", "ios"], []), "The plan says the registered timelines stay")
            update = {"mode": "update", "liveId": live_id, "jacket": {"kind": "keep"}, "audio": {"kind": "keep"},
                      "platforms": self.panel_platforms(plan)}
            EXPORTS.clear()
            job, summary = self.run_job(self.request(reopened, **update), managed=True)
            self.assertEqual(summary, register.NO_CHANGES)
            self.assertEqual(EXPORTS, [], "Kept without a bake")
            self.assertEqual(len(self.server_sessions), sessions, "A no-op update does not stop the server")
            self.assertEqual((job.song()["changed"], job.song()["restart"]), (False, "none"))
            # The registered value typed again: neither the fingerprint nor the parsed values match,
            # but the bake gives exactly the bytes the song plays, so nothing is written.
            reopened["tracks"][1]["events"][0]["values"]["intensity"] = 0.7
            plan = register.plan(self.root, reopened)
            self.assertEqual(plan["timeline"]["bake"], ["android", "ios"])
            job, summary = self.run_job(self.request(reopened, **update), managed=True)
            self.assertEqual(summary, register.NO_CHANGES)
            self.assertEqual([export["base"]["platform"] for export in EXPORTS], ["android", "ios"])
            self.assertEqual(len(self.server_sessions), sessions, "Equal bytes do not stop the server")
            # A real change still bakes, stops the server and writes.
            reopened["tracks"][1]["events"][0]["values"]["intensity"] = 0.9
            job, summary = self.run_job(self.request(reopened, **update), managed=True)
            self.assertEqual(job.song()["parts"], ["timeline"])
            self.assertEqual(len(self.server_sessions), sessions + 1)
        after = mv_studio_live.describe_mv_song(self.root, region="gl", live_id=live_id)
        self.assertEqual(after["platforms"], {"android": "custom", "ios": "custom"})

    def test_a_session_that_stopped_the_server_reports_it_without_changes(self):
        project = self.edited(self.project())
        first, _ = self.run_job(self.request(project), managed=True)
        live_id = first.song()["song"]["liveId"]
        linked = dict(project, registration={"region": "gl", "liveId": live_id})
        # The store finds nothing to change only after the stop (the job could not tell beforehand).
        with mock.patch.object(register, "_unchanged", return_value=False):
            job, summary = self.run_job(self.request(linked, mode="update", liveId=live_id, jacket={"kind": "keep"},
                                                     audio={"kind": "keep"}), managed=True)
        self.assertEqual(summary, register.NO_CHANGES)
        self.assertEqual(self.server_sessions[-1]["stop"], True)
        self.assertEqual((job.song()["changed"], job.song()["restart"]), (False, "done"))
        self.assertEqual(job.stages()[-1], "restart")

    def test_restart_state_reports_what_the_session_did(self):
        def session(**state):
            return type("Session", (), {"was_running": True, "restarted": False, "restart_pending": False, **state})()
        for current, managed, changed, expected in (
                (session(restarted=True), True, False, "done"), (session(restart_pending=True), True, False, "pending"),
                (session(), True, False, "stopped"), (session(was_running=False), True, False, "none"),
                (None, True, False, "none"), (session(restarted=True), True, True, "done"),
                (session(restart_pending=True), True, True, "pending"), (session(), True, True, "manual"),
                (None, False, True, "manual"), (None, False, False, "none")):
            with self.subTest(session=current and vars(type(current)), managed=managed, changed=changed):
                self.assertEqual(register._restart_state(current, managed, changed), expected)

    def test_a_removed_source_song_needs_a_stock_base(self):
        first, _ = self.run_job(self.request(self.edited(self.project())))
        live_id = first.song()["song"]["liveId"]
        reopened = self.reopened(live_id)
        self.assertEqual(register.plan(self.root, reopened)["target"], live_id)
        review = register.remove_plan(self.root, region="gl", live_id=live_id)
        register.run_remove(FakeJob(), self.root, register.validate_remove(
            {"region": "gl", "liveId": live_id, "reviewToken": review["reviewToken"]}))
        # The project's own song is gone: a blocked plan (not a failed request) that asks for a stock base.
        plan = register.plan(self.root, reopened)
        self.assertEqual((plan["region"], plan["base"], plan["song"], plan["targets"], plan["blocked"]),
                         ("gl", None, None, [], [{"message": register.SOURCE_REMOVED}]))
        self.assertEqual((plan["audio"]["default"], plan["timeline"]["unchanged"]), ("base", False))
        with self.assertRaisesRegex(ValueError, "was removed"):
            self.run_job(self.request(reopened))
        # A chosen stock base takes its place: the project's own timeline is then a mod of that base.
        template = {"region": "gl", "liveId": 21, "assetId": 2101}
        plan = register.plan(self.root, reopened, template=template)
        self.assertEqual((plan["base"]["liveId"], plan["base"]["fixed"], plan["timeline"]["kind"], plan["blocked"]),
                         (21, False, "mod", []))
        job, _ = self.run_job(self.request(reopened, template=template))
        self.assertEqual(job.song()["song"]["platforms"], {"android": "custom", "ios": "custom"})
        # A song that is still listed but cannot be read fails the check as before.
        listed = self.reopened(job.song()["song"]["liveId"])
        with mock.patch.object(mv_studio_live, "describe_mv_song", side_effect=ValueError("The game catalog is busy.")):
            with self.assertRaisesRegex(ValueError, "busy"):
                register.plan(self.root, listed)

    def test_a_song_that_took_a_removed_source_songs_id_is_not_the_source(self):
        keep = {"jacket": {"kind": "keep"}, "audio": {"kind": "keep"}}
        with store_clock(1_800_000_000):
            first, _ = self.run_job(self.request(self.edited(self.project())))
        live_id = first.song()["song"]["liveId"]
        reopened = self.reopened(live_id)
        self.assertEqual(reopened["source"]["registeredSong"],
                         {"revision": 1, "updatedAt": 1_800_000_000, "templateLiveId": 21})
        unkept = copy.deepcopy(reopened)
        del unkept["source"]["registeredSong"]
        # An update, here from another project of the same base MV, keeps it the song the project was opened from.
        with store_clock(1_800_000_060):
            self.run_job(self.request(self.edited(self.project(), keyframe=False, timing=True), mode="update",
                                      liveId=live_id, **keep))
        self.assertEqual(register.plan(self.root, reopened)["target"], live_id)
        reopened_later = self.reopened(live_id)
        self.assertEqual(reopened_later["source"]["registeredSong"]["revision"], 2)
        self.remove(live_id)
        # Another project of the same base MV registers a new song: the store gives it the removed song's ID.
        with store_clock(1_800_000_120):
            other, _ = self.run_job(self.request(self.edited(self.project(), keyframe=False), title="다른 곡"))
        self.assertEqual(other.song()["song"]["liveId"], live_id)
        # Opened at revision 1 (same revision, earlier update) and at revision 2 (a later revision): both are removed.
        for project in (reopened, reopened_later):
            plan = register.plan(self.root, project)
            self.assertEqual((plan["base"], plan["song"], plan["targets"], plan["blocked"]),
                             (None, None, [], [{"message": register.SOURCE_REMOVED}]))
            with self.assertRaisesRegex(ValueError, "was removed"):
                self.run_job(self.request(project, mode="update", liveId=live_id, **keep))
        self.assertEqual(self.songs()[0]["title"], "다른 곡")
        # A project opened before the song's identity was recorded follows the ID as before.
        self.assertEqual(register.plan(self.root, unkept)["target"], live_id)
        # The same revision and update time, another base MV: not the song the project was opened from.
        opened_other = self.reopened(live_id)
        self.remove(live_id)
        base22 = {"kind": "game", "region": "gl", "platform": "android", "liveId": 22, "assetId": 2201, "mvOnly": False,
                  "registered": False}
        with store_clock(1_800_000_120):
            third, _ = self.run_job(self.request(self.project(source=base22, native_bytes=self.local["tl2201"]),
                                                 title="세 번째 곡"))
        song = third.song()["song"]
        self.assertEqual((song["liveId"], song["revision"], song["updatedAt"], song["templateLiveId"]),
                         (live_id, 1, 1_800_000_120, 22))
        self.assertEqual(register.plan(self.root, opened_other)["blocked"], [{"message": register.SOURCE_REMOVED}])

    def test_a_game_import_records_the_registered_song_it_opens(self):
        from webtools.core import mv_studio_game
        with store_clock(1_800_000_000):
            job, _ = self.run_job(self.request(self.edited(self.project())))
        song = job.song()["song"]
        with closing(sqlite3.connect(self.root / "assets/db/gl/masterdata.db")) as master:
            self.assertEqual(mv_studio_game._registered_song(master, song["liveId"]), opened_song(song))
            self.assertEqual(opened_song(song), {"revision": 1, "updatedAt": 1_800_000_000, "templateLiveId": 21})
            self.assertIsNone(mv_studio_game._registered_song(master, 21), "A stock song is not registered")
        with closing(sqlite3.connect(":memory:")) as empty:
            self.assertIsNone(mv_studio_game._registered_song(empty, song["liveId"]), "No MV Studio songs table")
            # A first-version songs table: no revisions yet.
            empty.execute("CREATE TABLE _elichika_mv_studio_song (live_id INTEGER PRIMARY KEY, source_live_id INTEGER "
                          "NOT NULL, asset_3d_id INTEGER NOT NULL, title TEXT NOT NULL)")
            empty.execute("INSERT INTO _elichika_mv_studio_song VALUES (93000, 21, 9300001, 'old')")
            self.assertEqual(mv_studio_game._registered_song(empty, 93000),
                             {"revision": 0, "updatedAt": None, "templateLiveId": 21})

    def remove(self, live_id):
        review = register.remove_plan(self.root, region="gl", live_id=live_id)
        register.run_remove(FakeJob(), self.root, register.validate_remove(
            {"region": "gl", "liveId": live_id, "reviewToken": review["reviewToken"]}))

    def test_a_plan_made_before_an_edit_cannot_drop_the_edit(self):
        project = self.project()
        stale = register.plan(self.root, project)
        self.assertEqual(stale["timeline"]["bake"], [])
        edited = self.edited(project, timing=True)
        # The panel sends every catalogued platform, whatever the (stale) plan's bake list says.
        job, _ = self.run_job(self.request(edited, platforms=self.panel_platforms(stale)))
        self.assertEqual(job.song()["song"]["platforms"], {"android": "custom", "ios": "custom"})
        # A request that leaves out a platform the user never agreed to leave at the original MV is refused.
        for platforms, download in (([], False), (["android"], False), (["android"], True)):
            with self.subTest(platforms=platforms, download=download):
                with self.assertRaisesRegex(ValueError, "The project changed after the last check"):
                    self.run_job(self.request(edited, platforms=platforms, download=download))
        self.assertEqual(len(self.songs()), 1)
        # Without edits, a left-out platform plays the original MV anyway: nothing to refuse.
        job, _ = self.run_job(self.request(self.project(), platforms=[]))
        self.assertEqual(job.song()["song"]["platforms"], {"android": "stock", "ios": "stock"})

    def test_a_mod_project_may_leave_out_its_other_platform(self):
        mod_tracks = base_tracks()
        mod_tracks[1]["events"][0]["values"]["intensity"] = 1.75
        mod = self.project(source={"kind": "mod"}, tracks=mod_tracks,
                           native_bytes=timeline_bytes("ios", mod_tracks, tag="mod"))
        template = {"region": "gl", "liveId": 21, "assetId": 2101}
        with mock.patch.object(register, "_export", side_effect=lambda raw, name, tracks: (
                (_ for _ in ()).throw(ValueError("no slot")) if json.loads(raw[8:].rstrip(b" "))["platform"] == "android"
                else fake_export(raw, name, tracks))):
            with self.assertRaisesRegex(ValueError, "Register for iOS only"):
                self.run_job(self.request(mod, template=template))
            job, _ = self.run_job(self.request(mod, template=template, platforms=["ios"]))
        self.assertEqual(job.song()["song"]["platforms"], {"android": "stock", "ios": "custom"})
        with self.assertRaisesRegex(ValueError, "The project changed after the last check"):
            self.run_job(self.request(mod, template=template, platforms=["android"]))

    def test_update_of_a_registered_import_bakes_against_the_template_stock(self):
        first, _ = self.run_job(self.request(self.edited(self.project())))
        live_id = first.song()["song"]["liveId"]
        EXPORTS.clear()
        registered = self.project(source={"kind": "game", "region": "gl", "platform": "android", "liveId": live_id,
                                          "assetId": live_id * 100 + 1, "registered": True},
                                  tracks=self.edited(self.project())["tracks"],
                                  native_bytes=timeline_bytes("android", tag="custom"))
        registered["tracks"][2]["events"][0]["values"]["color"] = {"r": 0.5, "g": 1, "b": 1, "a": 1}
        job, summary = self.run_job(self.request(registered, mode="update", liveId=live_id, jacket={"kind": "keep"},
                                                 audio={"kind": "keep"}, title="새 제목"))
        self.assertEqual(summary, register.UPDATED.replace("{title}", "새 제목").replace("{id}", str(live_id)))
        self.assertEqual([export["base"]["tag"] for export in EXPORTS], ["stock", "stock"])
        self.assertEqual(job.song()["parts"], ["timeline", "title"])
        self.assertEqual(job.song()["song"]["title"], "새 제목")

    def test_missing_ios_original_needs_download_or_consent(self):
        del self.local["tl2101i"]
        project = self.edited(self.project())
        with self.assertRaisesRegex(ValueError, "original iOS timeline is not available"):
            self.run_job(self.request(project))
        self.assertEqual(self.songs(), [])
        job, _ = self.run_job(self.request(project, platforms=["android"]))
        self.assertEqual(job.song()["song"]["platforms"], {"android": "custom", "ios": "stock"})
        self.remote["tl2101i"] = timeline_bytes("ios")
        job, _ = self.run_job(self.request(self.edited(self.project()), download=True))
        self.assertEqual(job.song()["song"]["platforms"], {"android": "custom", "ios": "custom"})
        self.assertIn(("tl2101i", True), self.loads)
        self.assertIn(("ios", "ios", 9), self.validated, "The downloaded original validated the iOS bake")

    def test_mod_project_bakes_its_own_platform_on_the_mod_timeline(self):
        mod_tracks = base_tracks()
        mod_tracks[1]["events"][0]["values"]["intensity"] = 1.75
        mod = self.project(source={"kind": "mod"}, tracks=mod_tracks,
                           native_bytes=timeline_bytes("ios", mod_tracks, tag="mod"))
        job, _ = self.run_job(self.request(mod, template={"region": "gl", "liveId": 21, "assetId": 2101}))
        self.assertEqual([(export["base"]["platform"], export["base"]["tag"]) for export in EXPORTS],
                         [("android", "stock"), ("ios", "mod")])
        self.assertEqual(job.song()["song"]["platforms"], {"android": "custom", "ios": "custom"})

    def test_remove_always_stops_the_server_and_uses_the_review_token(self):
        first, _ = self.run_job(self.request(self.project()))
        live_id = first.song()["song"]["liveId"]
        review = register.remove_plan(self.root, region="gl", live_id=live_id)
        self.assertEqual(review["blocked"], [])
        job = FakeJob()
        with mock.patch.object(register, "managed", return_value=False):
            summary = register.run_remove(job, self.root, register.validate_remove(
                {"region": "gl", "liveId": live_id, "reviewToken": review["reviewToken"]}))
        self.assertEqual(summary, register.REMOVED.replace("{title}", "내 MV").replace("{id}", str(live_id)))
        self.assertEqual(self.server_sessions, [{"stop": True, "restart": False, "exports": 0}])
        removed = next(event for event in job.events if event["type"] == "mv-song-removed")
        self.assertEqual(removed["restart"], "stopped")
        self.assertEqual(self.songs(), [])
        with self.assertRaisesRegex(ValueError, "removal review is out of date"):
            register.validate_remove({"region": "gl", "liveId": live_id, "reviewToken": "x"})

    def test_cancel_before_the_database_step_writes_nothing(self):
        job = FakeJob()
        job.cancel_event.set()
        with mock.patch.object(register, "managed", return_value=False):
            summary = register.run_register(job, self.root, self.request(self.edited(self.project())))
        self.assertEqual(summary, register.CANCELLED)
        self.assertEqual(self.songs(), [])

    def test_fix_adds_the_placeholder_to_a_legacy_song(self):
        with database_maintenance.guard(self.root):
            legacy = mv_studio_live.register_mv_song(self.root, region="gl", live_id=None, template_live_id=21,
                                                     template_asset_id=2101, title="Old", log=None)
        live_id = legacy["liveId"]
        placeholder = live_id * 1000 + 301
        with closing(sqlite3.connect(self.root / "assets/db/gl/masterdata.db")) as database, database:
            database.execute("DELETE FROM m_live_difficulty WHERE live_id=?", (live_id,))
            database.execute("DELETE FROM m_live_difficulty_const WHERE id=?", (placeholder,))
            database.execute("DELETE FROM m_live_difficulty_mission WHERE live_difficulty_master_id=?", (placeholder,))
        (self.root / "assets/stages" / f"{placeholder}.json").unlink()
        self.assertEqual(mv_studio_live.describe_mv_song(self.root, region="gl", live_id=live_id)["actions"],
                         ["fix", "remove"])
        request = register.validate_register(self.root, {"mode": "update", "region": "gl", "liveId": live_id,
                                                         "addPlaceholder": True})
        job, _ = self.run_job(request)
        self.assertEqual(job.song()["parts"], ["placeholder"])
        self.assertTrue(job.song()["song"]["visible"])

    def test_project_audio_is_encoded_before_the_store_and_kept_on_update(self):
        calls = []

        def make_cue(pcm, acb, awb, *, sheet, beat, progress=None, scratch_dir=None, **_):
            calls.append(("cue", sheet, beat, len(pcm)))
            progress(1, 1)
            return {"acb": f"ACB:{sheet}".encode(), "awb": b"AFS2music", "sampleCount": len(pcm), "snrDb": 30.0}

        def make_preview(pcm, acb, awb, *, sheet, start_seconds, beat, length_samples=None, scratch_dir=None, **_):
            calls.append(("preview", sheet, start_seconds, length_samples))
            return {"acb": f"ACB:{sheet}".encode(), "awb": b"AFS2sabi", "sampleCount": 10, "snrDb": 30.0,
                    "startSample": 0}

        def audio_cue(acb, awb):
            return bytes(acb)[4:].decode()

        from webtools.core import cri_acb_write
        self.local.update(m21acb=b"@UTF music", m21awb=b"AFS2 music", sabi21a=b"@UTF sabi", sabi21w=b"AFS2 sabi")
        pcm = register.store_pcm(wav_bytes(44100 * 2))
        audio = {"kind": "project", "pcm": pcm["name"], "bpm": 128, "firstBeat": 0.5, "previewStart": 1}
        with mock.patch.object(register, "encoder_available", return_value=True), \
                mock.patch.object(cri_acb_write, "make_cue", side_effect=make_cue), \
                mock.patch.object(cri_acb_write, "make_preview", side_effect=make_preview), \
                mock.patch.object(cri_acb_write, "template_info", return_value={"sampleCount": 882000}), \
                mock.patch.object(native, "audio_cue", side_effect=audio_cue):
            job, _ = self.run_job(self.request(self.project(), audio=audio))
            song = job.song()["song"]
            live_id = song["liveId"]
            self.assertEqual(calls, [("cue", f"music_{live_id}", {"bpm": 128.0, "firstBeat": 0.5}, 88200),
                                     ("preview", f"music_{live_id}_SABI", 1.0, 882000)])
            self.assertEqual((song["audio"], song["musicSheet"], song["previewSheet"]),
                             ("custom", f"music_{live_id}", f"music_{live_id}_SABI"))
            self.assertEqual(job.stages(), ["check", "audio", "preview", "write"])
            calls.clear()
            again, summary = self.run_job(self.request(self.project(), mode="update", liveId=live_id, audio=audio,
                                                       jacket={"kind": "keep"}))
        self.assertEqual((summary, calls), (register.NO_CHANGES, []))


def forbid_real_server_kills(case, serverctl):
    """Fail ``case`` instead of running serverctl's standalone stop. Without a registered controller,
    installation_server SIGKILLs every process named like an Elichika server on this machine (pkill,
    or the /proc scan), which would kill the maintainer's running game server or the test's own shell."""
    reached = []

    def refuse(*_args, **_kwargs):
        reached.append(case.id())
        raise AssertionError("The test reached serverctl's real process kill: register a stand-in controller")

    for name in ("_pkill", "_proc_kill"):
        patcher = mock.patch.object(serverctl, name, side_effect=refuse)
        patcher.start()
        case.addCleanup(patcher.stop)
    case.addCleanup(lambda: case.assertEqual(reached, [], "The test reached serverctl's real process kill"))


class Controller:
    """The app's server controller as adminui.serverctl drives it. ``deferred`` behaves like the
    Android/macOS job reservation: start() inside a job only asks for a restart, finish_job runs it."""

    def __init__(self, *, deferred=False, on_start=None, begin=True):
        self.running, self.calls, self.deferred, self.requested = True, [], deferred, False
        self.on_start, self.begin = on_start, begin

    def is_running(self):
        return self.running

    def stop(self):
        self.calls.append("stop")
        self.running = False
        return True

    def start(self):
        self.calls.append("start")
        if self.on_start:
            self.on_start()
        if self.deferred:
            self.requested = True
        else:
            self.running = True
        return True

    def restart_is_pending(self):
        return self.deferred and self.requested

    def finish(self):
        self.calls.append("finish")

    def begin_job(self):
        self.calls.append("begin_job")
        return self.begin

    def finish_job(self, successful):
        self.calls.append(f"finish_job:{successful}")
        if successful and self.requested:
            self.running = True
        self.requested = False
        return True


@NEEDS_STORE
class JobLifecycleTests(Case):
    """Real installation_server / whole_job_server with a stand-in controller, under the plain
    webtools job manager and the app's guarded one."""

    def setUp(self):
        super().setUp()
        from adminui import serverctl
        self.serverctl = serverctl
        self.addCleanup(serverctl.register_controller, None)
        forbid_real_server_kills(self, serverctl)
        for name, value in (("_server_session", REAL_SERVER_SESSION), ("_lifecycle", REAL_LIFECYCLE)):
            patcher = mock.patch.object(register, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def controller(self, **options):
        controller = Controller(**options)
        self.serverctl.register_controller(controller)
        return controller

    def run_with(self, manager, body):
        job = manager.create("mv_test")
        manager.run_async(job, body)
        for _ in range(400):
            if job.is_done:
                break
            threading.Event().wait(0.05)
        events = [job.event_at(index, 0) for index in range(job.event_count)]
        return job, events

    def plain(self):
        from webtools.jobs import JobManager
        return JobManager()

    def guarded(self):
        from adminui.jobs import JobManager
        patcher = mock.patch.object(register, "_guarded_manager", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        return JobManager(root=self.root)

    def registered(self):
        controller = Controller()
        self.serverctl.register_controller(controller)
        job = FakeJob()
        register.run_register(job, self.root, self.request(self.edited(self.project())))
        self.serverctl.register_controller(None)
        return job.song()["song"]["liveId"]

    def racing_remove(self, live_id):
        """The review goes out of date between the job's own check and the removal (a player's record)."""
        real = mv_studio_live.remove_mv_song

        def remove(*args, **kwargs):
            with closing(sqlite3.connect(self.root / "userdata.db")) as database, database:
                database.execute("INSERT INTO u_live_mv_deck VALUES (2, ?, NULL)", (live_id,))
            return real(*args, **kwargs)
        return mock.patch.object(mv_studio_live, "remove_mv_song", side_effect=remove)

    def remove_request(self, live_id):
        review = register.remove_plan(self.root, region="gl", live_id=live_id)
        return register.validate_remove({"region": "gl", "liveId": live_id, "reviewToken": review["reviewToken"]})

    def failed(self, events):
        return [event for event in events if event["type"] == "mv-failed"]

    def test_an_out_of_date_review_is_refused_before_the_server_stops(self):
        live_id = self.registered()
        request = self.remove_request(live_id)
        # A player's record changes after the review was taken (the game server kept running).
        with closing(sqlite3.connect(self.root / "userdata.db")) as database, database:
            database.execute("INSERT INTO u_live_mv_deck VALUES (3, ?, NULL)", (live_id,))
        controller = self.controller()
        job, events = self.run_with(self.plain(), lambda job: register.run_remove(job, self.root, request))
        self.assertEqual((events[-1]["status"], events[-1]["summary"]), ("error", register.REVIEW_OUT_OF_DATE))
        self.assertNotIn("stop", controller.calls)
        self.assertTrue(controller.running)
        self.assertEqual(len(mv_studio_live.list_mv_songs(self.root, region="gl")), 1)

    def test_a_refusal_after_the_stop_restarts_the_managed_server(self):
        live_id = self.registered()
        request = self.remove_request(live_id)
        controller = self.controller()
        with self.racing_remove(live_id):
            job, events = self.run_with(self.plain(), lambda job: register.run_remove(job, self.root, request))
        self.assertEqual((events[-1]["status"], events[-1]["summary"]), ("error", register.REVIEW_OUT_OF_DATE))
        self.assertEqual(self.failed(events), [{"type": "mv-failed", "message": register.REVIEW_OUT_OF_DATE,
                                                "restart": "done"}])
        self.assertEqual(controller.calls[:3], ["begin_job", "stop", "start"])
        self.assertTrue(controller.running, "Nothing was written, so the game server runs again")
        self.assertEqual(len(mv_studio_live.list_mv_songs(self.root, region="gl")), 1)
        self.assertFalse(register.busy())

    def test_a_refusal_under_the_app_job_manager_lets_the_app_restart_the_server(self):
        live_id = self.registered()
        request = self.remove_request(live_id)
        controller = self.controller(deferred=True)
        manager = self.guarded()
        with self.racing_remove(live_id):
            job, events = self.run_with(manager, lambda job: register.run_remove(job, self.root, request))
        self.assertEqual(self.failed(events), [{"type": "mv-failed", "message": register.REVIEW_OUT_OF_DATE,
                                                "restart": "pending"}])
        self.assertEqual(events[-1]["status"], "done", "The job ends normally so the app runs the restart")
        self.assertIn("finish_job:True", controller.calls)
        self.assertTrue(controller.running)
        self.assertEqual(len(mv_studio_live.list_mv_songs(self.root, region="gl")), 1)

    def test_an_unexpected_failure_after_the_stop_reports_the_stopped_server(self):
        controller = self.controller()
        with mock.patch.object(mv_studio_live, "register_mv_song", side_effect=sqlite3.OperationalError("disk I/O error")):
            job, events = self.run_with(self.plain(), lambda job: register.run_register(
                job, self.root, self.request(self.edited(self.project()))))
        self.assertEqual(events[-1]["status"], "error")
        self.assertEqual(self.failed(events), [{"type": "mv-failed", "message": "disk I/O error", "restart": "stopped"}])
        self.assertEqual(controller.calls[:2], ["begin_job", "stop"])
        self.assertNotIn("start", controller.calls)
        self.assertFalse(controller.running)

    def test_a_cancel_during_the_restart_keeps_the_registration_and_the_restart(self):
        for deferred, manager in ((False, self.plain), (True, self.guarded)):
            with self.subTest(deferred=deferred):
                holder = {}
                controller = self.controller(deferred=deferred, on_start=lambda: holder["job"].cancel_event.set())
                chosen = manager()
                job = chosen.create("mv_register")
                holder["job"] = job
                request = self.request(self.edited(self.project()))
                chosen.run_async(job, lambda job: register.run_register(job, self.root, request))
                for _ in range(400):
                    if job.is_done:
                        break
                    threading.Event().wait(0.05)
                events = [job.event_at(index, 0) for index in range(job.event_count)]
                self.assertEqual(events[-1]["status"], "done", events[-1])
                self.assertTrue(any(event["type"] == "mv-song" for event in events))
                self.assertTrue(controller.running, controller.calls)

    def test_a_job_the_app_refuses_before_its_body_does_not_hold_the_slot(self):
        self.controller(begin=False)
        manager = self.guarded()
        job, events = self.run_with(manager, lambda job: register.run_register(
            job, self.root, self.request(self.project())))
        self.assertEqual(events[-1]["status"], "error")
        self.assertFalse(register.busy())
        self.assertTrue(register.reserve())
        register.release()

    def test_a_second_job_is_refused_while_one_runs(self):
        self.assertTrue(register.reserve())
        try:
            with self.assertRaisesRegex(ValueError, "Another MV registration or removal is running"):
                register.run_register(FakeJob(), self.root, self.request(self.project()))
            self.assertTrue(register.busy(), "The refused job leaves the running job's slot alone")
        finally:
            register.release()


@NEEDS_STORE
class RealEncoderTests(Case):
    """Project audio through the real HCA encoder and ACB/AWB writer, accepted by Elichika's own cue check."""

    def setUp(self):
        super().setUp()
        sys.path.insert(0, str(REPO / "tests"))
        self.addCleanup(sys.path.remove, str(REPO / "tests"))
        import test_cri_acb_write as cri_tests
        from webtools.core import cri_hca_encode
        try:
            library = cri_tests.Clhca.get()
        except unittest.SkipTest:
            raise
        environment = mock.patch.dict(os.environ, {"ELICHIKA_HCA_LIBRARY": library})
        environment.start()
        self.addCleanup(environment.stop)
        music_acb, music_awb = cri_tests.synthetic_template(cri_hca_encode.encode_hca(cri_tests.tone(1.0, 200)))
        sabi_acb, sabi_awb = cri_tests.synthetic_template(cri_hca_encode.encode_hca(cri_tests.tone(0.5, 300)))
        self.local.update(m21acb=music_acb, m21awb=music_awb, sabi21a=sabi_acb, sabi21w=sabi_awb)
        self.tone = cri_tests.tone

    def test_project_audio_registers_a_music_cue_and_its_preview(self):
        from webtools.core import cri_audio_decode
        import struct
        pcm = self.tone(6.0, 330, 440, level=0.3)
        data = pcm.tobytes()
        wav = (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 2, 44100,
               176400, 4, 16) + b"data" + struct.pack("<I", len(data)) + data)
        name = register.store_pcm(wav)["name"]
        self.assertTrue(register.encoder_available())
        audio = {"kind": "project", "pcm": name, "bpm": 128, "firstBeat": 0.25, "previewStart": 1.0}
        job, _ = self.run_job(self.request(self.project(), audio=audio))
        song = job.song()["song"]
        sheet = f"music_{song['liveId']}"
        self.assertEqual((song["audio"], song["musicSheet"], song["previewSheet"]), ("custom", sheet, sheet + "_SABI"))
        self.assertTrue(any(event["type"] == "mv-encode" for event in job.events))
        with closing(sqlite3.connect(self.root / "assets/db/gl/asset_a_en.db")) as database:
            rows = dict((row[0], row[1:]) for row in database.execute(
                "SELECT sheet_name, acb_pack_name, awb_pack_name FROM m_asset_sound WHERE sheet_name LIKE ?", (sheet + "%",)))
        self.assertEqual(sorted(rows), [sheet, sheet + "_SABI"])
        acb = (self.root / "static" / rows[sheet][0]).read_bytes()
        self.assertEqual(cri_audio_decode.inspect_cues(acb)["sheet"], sheet)
        beat = cri_audio_decode.inspect_beat_sync(acb, sheet)
        self.assertEqual((beat["bpm"], beat["startSample"]), (128.0, round(0.25 * 44100)))


@NEEDS_STORE
class RequestTests(Case):
    def test_request_validation(self):
        project = self.project()
        with self.assertRaisesRegex(ValueError, "song title"):
            self.request(project, title=" ")
        with self.assertRaisesRegex(ValueError, "song title"):
            self.request(project, title="x" * 161)
        self.assertEqual(self.request(project, title="  x" + "y" * 158)["title"], "x" + "y" * 158)
        with self.assertRaisesRegex(ValueError, "credit"):
            self.request(project, credit="a\nb")
        with self.assertRaisesRegex(ValueError, "no registered part to keep"):
            self.request(project, audio={"kind": "keep"})
        with self.assertRaisesRegex(ValueError, "no registered part to keep"):
            self.request(project, jacket={"kind": "keep"})
        with mock.patch.object(register, "encoder_available", return_value=False):
            with self.assertRaisesRegex(ValueError, "only the original audio or prepared ACB/AWB"):
                self.request(project, audio={"kind": "project", "pcm": "a" * 32 + ".wav", "bpm": 120, "firstBeat": 0})
        with mock.patch.object(register, "encoder_available", return_value=True):
            with self.assertRaisesRegex(ValueError, "Enter the BPM and the first beat"):
                self.request(project, audio={"kind": "project", "pcm": "a" * 32 + ".wav"})
            with self.assertRaisesRegex(ValueError, "Enter a BPM between"):
                self.request(project, audio={"kind": "project", "pcm": "a" * 32 + ".wav", "bpm": 0, "firstBeat": 0})
        files = self.request(project, audio={"kind": "files", "acbPath": self.jacket_file("x.acb", b"@UTF"),
                                             "awbPath": self.jacket_file("x.awb", b"AFS2")})
        self.assertEqual(files["audio"]["kind"], "files")
        self.assertEqual(self.request(project, platforms=[])["platforms"], ())
        with self.assertRaisesRegex(ValueError, "Choose Android, iOS or both."):
            self.request(project, platforms=["android", "android"])
        with self.assertRaisesRegex(ValueError, "not baked"):
            self.request(project, unbaked=[{"kind": "camera"}])
        with self.assertRaisesRegex(ValueError, "Choose a new song"):
            self.request(project, mode="update")


# ---------------------------------------------------------------- endpoints

@NEEDS_STORE
class EndpointTests(Case):
    def setUp(self):
        super().setUp()
        from http.server import ThreadingHTTPServer
        from webtools import server
        cwd = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, cwd)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.httpd.daemon_threads = True
        thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.port = self.httpd.server_address[1]

    def call(self, method, path, body=None, *, headers=None, raw=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        payload = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        sent = {"Host": f"127.0.0.1:{self.port}"}
        if payload is not None:
            sent.update({"Content-Type": "application/json", "Content-Length": str(len(payload))})
        sent.update(headers or {})
        connection.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        for key, value in sent.items():
            connection.putheader(key, value)
        connection.endheaders()
        if payload:
            connection.send(payload)
        response = connection.getresponse()
        data = json.loads(response.read() or b"null")
        connection.close()
        return response.status, data

    def test_songs_plan_and_host_rules(self):
        status, data = self.call("GET", "/api/mv-studio/songs?region=gl")
        self.assertEqual((status, data["songs"]), (200, []))
        self.assertIn("encoder", data)
        status, data = self.call("GET", "/api/mv-studio/songs?region=gl", headers={"Host": "evil.example"})
        self.assertEqual(status, 403)
        status, data = self.call("POST", "/api/mv-studio/registration-plan", {"project": self.project()},
                                 headers={"Origin": "http://evil.example"})
        self.assertEqual(status, 403)
        status, data = self.call("POST", "/api/mv-studio/registration-plan", {"project": self.project()},
                                 headers={"Origin": f"http://127.0.0.1:{self.port}"})
        self.assertEqual((status, data["base"]["liveId"]), (200, 21))
        status, data = self.call("POST", "/api/mv-studio/register", {"region": "gl"})
        self.assertEqual(status, 404, "The old single-button endpoint is gone")

    def test_pcm_upload_limits(self):
        status, data = self.call("POST", "/api/mv-studio/pcm", raw=wav_bytes(4410),
                                 headers={"Content-Type": "audio/wav"})
        self.assertEqual((status, data["duration"]), (200, 0.1))
        status, data = self.call("POST", "/api/mv-studio/pcm", raw=b"RIFF0000WAVEjunk!",
                                 headers={"Content-Type": "audio/wav"})
        self.assertEqual(status, 400)
        status, data = self.call("POST", "/api/mv-studio/pcm", raw=wav_bytes(10), headers={"Content-Type": "text/plain"})
        self.assertEqual(status, 400)
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        connection.putrequest("POST", "/api/mv-studio/pcm", skip_host=True)
        for key, value in {"Host": f"127.0.0.1:{self.port}", "Content-Type": "audio/wav",
                           "Content-Length": str(register.PCM_BYTES + 1)}.items():
            connection.putheader(key, value)
        connection.endheaders()
        response = connection.getresponse()
        self.assertEqual(response.status, 400)
        self.assertIn("96 MiB", json.loads(response.read())["error"])
        connection.close()

    def test_busy_and_missing_elichika(self):
        body = {"mode": "new", "project": self.project(), "title": "x", "jacket": {"kind": "base"},
                "audio": {"kind": "base"}, "platforms": []}
        self.assertTrue(register.reserve())
        try:
            status, data = self.call("POST", "/api/mv-studio/register-job", body)
        finally:
            register.release()
        self.assertEqual((status, data["error"]), (409, register.BUSY))
        held, release = threading.Event(), threading.Event()

        def hold():
            with database_maintenance.guard(self.root):
                held.set()
                release.wait(10)

        holder = threading.Thread(target=hold)
        holder.start()
        held.wait(10)
        try:
            status, data = self.call("POST", "/api/mv-studio/register-job", body)
        finally:
            release.set()
            holder.join()
        self.assertEqual(status, 409)
        self.assertTrue(register.reserve(), "A refused job gives the slot back")
        register.release()
        with mock.patch.object(register, "store", side_effect=ImportError):
            status, data = self.call("GET", "/api/mv-studio/songs?region=gl")
        self.assertEqual((status, data["error"]), (501, register.NO_ELICHIKA))

    def test_register_job_language_is_read_with_the_request(self):
        from webtools.jobs import MANAGER
        seen = []
        with mock.patch.object(register, "run_register", side_effect=lambda job, root, request, *, language:
                               seen.append(language) or "ok"):
            status, data = self.call("POST", "/api/mv-studio/register-job?lang=ko",
                                     {"mode": "new", "project": self.project(), "title": "x", "jacket": {"kind": "base"},
                                      "audio": {"kind": "base"}, "platforms": ["android", "ios"]})
            self.assertEqual(status, 200)
            job = MANAGER.get(data["job_id"])
            for _ in range(200):
                if job.is_done:
                    break
                threading.Event().wait(0.05)
        self.assertEqual(seen, ["ko"])

    def test_register_job_runs_and_reports_the_song(self):
        from webtools.jobs import MANAGER
        body = {"mode": "new", "project": self.edited(self.project()), "title": "내 MV", "jacket": {"kind": "base"},
                "audio": {"kind": "base"}, "platforms": ["android", "ios"]}
        with mock.patch.object(register, "managed", return_value=False):
            status, data = self.call("POST", "/api/mv-studio/register-job", body)
            self.assertEqual(status, 200)
            job = MANAGER.get(data["job_id"])
            for _ in range(200):
                if job.is_done:
                    break
                threading.Event().wait(0.05)
        events = [job.event_at(index, 0) for index in range(job.event_count)]
        self.assertEqual(events[-1]["status"], "done", events)
        song = next(event for event in events if event["type"] == "mv-song")["song"]
        self.assertEqual(song["platforms"], {"android": "custom", "ios": "custom"})
        status, data = self.call("POST", "/api/mv-studio/songs/remove-plan", {"region": "gl", "liveId": song["liveId"]})
        self.assertEqual((status, data["blocked"]), (200, []))
        self.assertRegex(data["reviewToken"], r"\A[0-9a-f]{64}\Z")


# ---------------------------------------------------------------- translations

class MessageTests(unittest.TestCase):
    def encoder_messages(self):
        from webtools.core import cri_acb_write, cri_hca_encode
        messages = set()
        for module in (cri_hca_encode, cri_acb_write):
            tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
            raisers = {"_fail": 0, "AudioEncodeError": 0, "_array": 1}
            helpers = {id(node) for function in ast.walk(tree)
                       if isinstance(function, ast.FunctionDef) and function.name in raisers for node in ast.walk(function)}
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call) and id(node) not in helpers and isinstance(node.func, ast.Name)
                        and node.func.id in raisers):
                    messages.add(node.args[raisers[node.func.id]].value)
        return messages

    def assert_translated(self, messages):
        for message in sorted(messages):
            for language in ("ko", "ja"):
                with self.subTest(language=language, message=message):
                    self.assertIn(message, i18n._TABLES[language])
                    if not message.isascii() or any(char.islower() for char in message):
                        self.assertNotEqual(i18n.tr(message, language), message)

    def test_every_panel_string_has_korean_and_japanese(self):
        script = (REPO / "webtools/web/static/mv-studio-register.js").read_text(encoding="utf-8")
        start = script.index("const STRINGS = Object.freeze([") + len("const STRINGS = Object.freeze([")
        strings = ast.literal_eval("[" + script[start:script.index("]);", start)] + "]")
        self.assertGreater(len(strings), 80)
        self.assert_translated(set(strings))
        # Every t()/format()/button()/field() literal of the module is listed.
        import re
        used = set(re.findall(r'(?:\bt|format|button|ctx\.field)\(\s*"([^"]+)"', script))
        self.assertEqual(sorted(used - set(strings)), [])

    def test_registration_and_encoder_messages_have_korean_and_japanese(self):
        self.assert_translated(set(register.MESSAGES) | self.encoder_messages())

    @NEEDS_STORE
    def test_every_elichika_store_message_has_korean_and_japanese(self):
        self.assert_translated(set(mv_studio_live.MESSAGES) | {database_maintenance.BusyError().args[0],
                                                               database_maintenance.LockError().args[0]})


# ---------------------------------------------------------------- real samples (optional)

@NEEDS_STORE
@unittest.skipUnless((SAMPLES / "a-1203503-live_timeline.unity").is_file()
                     and (SAMPLES / "i-1203503-live_timeline.unity").is_file(), "Original game samples are optional")
class RealSampleTests(unittest.TestCase):
    def test_12035_camera_and_bloom_edits_pass_the_store_validator_on_both_platforms(self):
        import time
        raw = {platform: (SAMPLES / f"{prefix}-1203503-live_timeline.unity").read_bytes()
               for platform, prefix in (("android", "a"), ("ios", "i"))}
        register._PARSED.clear()
        original = register._parse(raw["android"])
        self.assertEqual(original["tracks"], register._parse(raw["ios"])["tracks"])
        tracks = copy.deepcopy(original["tracks"])
        camera = next(event for track in tracks if track["kind"] == "camera" for event in track["events"]
                      if "keyframes" in event["editableValues"])
        for point in camera["values"]["keyframes"][:30]:
            point["fov"] = point["fov"] + 2
        bloom = next(event for track in tracks if track["nativeClass"] == "LiveBloomTrack" for event in track["events"]
                     if "intensity" in event["editableValues"])
        bloom["values"]["intensity"] = bloom["values"]["intensity"] + 0.5
        tracks[0]["muted"] = not tracks[0]["muted"]
        normalized, report = register.normalize(original["tracks"], tracks)
        self.assertEqual(report["trackSettings"], [tracks[0]["label"]])
        self.assertEqual(register.count_edits(original["tracks"], normalized)["cameraShots"], 1)
        outputs = {platform: register._export(raw[platform], "registration test", normalized) for platform in raw}
        for platform, output in outputs.items():
            native._validate_timeline(output, raw[platform], native.PLATFORMS[platform][1], time.monotonic() + 120)
        self.assertEqual(register._parse(outputs["android"])["tracks"], register._parse(outputs["ios"])["tracks"])



@NEEDS_STORE
@unittest.skipUnless((SAMPLES / "a-1203503-live_timeline.unity").is_file()
                     and (SAMPLES / "i-1203503-live_timeline.unity").is_file(), "Original game samples are optional")
class RealSampleUpdateTests(Case):
    """Real 12035 originals as the base MV's stock (Android and iOS) through the real timeline parser
    and writer, the store's validator and installation_server with a stand-in controller."""

    def setUp(self):
        super().setUp()
        self.local["tl2101"] = (SAMPLES / "a-1203503-live_timeline.unity").read_bytes()
        self.local["tl2101i"] = (SAMPLES / "i-1203503-live_timeline.unity").read_bytes()
        from adminui import serverctl
        self.serverctl = serverctl
        self.addCleanup(serverctl.register_controller, None)
        forbid_real_server_kills(self, serverctl)
        self.exports = []

        def export(raw, name, tracks):
            self.exports.append(name)
            return REAL_EXPORT(raw, name, tracks)

        for target, name, value in ((mv_studio_timeline, "parse_timeline", REAL_PARSE),
                                    (mv_studio_timeline, "export_timeline", export),
                                    (register, "_blob_platform", REAL_BLOB_PLATFORM),
                                    (native, "_validate_timeline", REAL_VALIDATE),
                                    (register, "_server_session", REAL_SERVER_SESSION),
                                    (register, "_lifecycle", REAL_LIFECYCLE)):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def imported(self, raw, source):
        """The project MV Studio's game import makes of a timeline (with its preview parse options)."""
        path = self.temp / f"timeline-{len(list(self.temp.glob('timeline-*')))}.unity"
        path.write_bytes(raw)
        return self.project(platform=source["platform"], source=source, tracks=mv_studio._timeline(path)[1]["tracks"],
                            native_bytes=raw)

    def job(self, request):
        """One register job with the app controlling the game server: (job, summary, controller calls)."""
        controller = Controller()
        self.serverctl.register_controller(controller)
        try:
            job = FakeJob()
            summary = register.run_register(job, self.root, request)
        finally:
            self.serverctl.register_controller(None)
        return job, summary, controller.calls

    @staticmethod
    def bloom(project):
        return next(event for track in project["tracks"] if track["nativeClass"] == "LiveBloomTrack"
                    for event in track["events"] if "intensity" in event["editableValues"])

    def test_12035_a_mute_only_project_registers_the_mute_on_both_platforms(self):
        stock = {"kind": "game", "region": "gl", "platform": "android", "liveId": 21, "assetId": 2101,
                 "mvOnly": False, "registered": False}
        project = self.imported(self.local["tl2101"], stock)
        leaf = next(track for track in project["tracks"] if track["events"] and not track["muted"]
                    and mv_studio_timeline.track_mute_refusal(track) is None)
        leaf["muted"] = True
        plan = register.plan(self.root, project)
        self.assertEqual((plan["edits"]["clips"], plan["edits"]["tracks"]), (0, 1))
        self.assertEqual((plan["timeline"]["unchanged"], plan["timeline"]["bake"], plan["blocked"]),
                         (False, ["android", "ios"], []))
        job, _, _ = self.job(self.request(project, title="음소거 곡"))
        song = mv_studio_live.describe_mv_song(self.root, region="gl", live_id=job.song()["song"]["liveId"])
        self.assertEqual(song["platforms"], {"android": "custom", "ios": "custom"})
        self.assertEqual(len(self.exports), 2)
        for platform, raw in register._registered_timelines(self.root, song).items():
            with self.subTest(platform=platform):
                tracks = {track["id"]: track for track in REAL_PARSE(raw, platform)["tracks"]}
                self.assertIs(tracks[leaf["id"]]["muted"], True)
                self.assertEqual(sum(track["muted"] for track in tracks.values()),
                                 1 + sum(track["muted"] for track in REAL_PARSE(self.local["tl2101"], "a")["tracks"]))

    def test_12035_update_after_opening_the_registered_song_never_stops_the_server(self):
        stock = {"kind": "game", "region": "gl", "platform": "android", "liveId": 21, "assetId": 2101,
                 "mvOnly": False, "registered": False}
        project = self.imported(self.local["tl2101"], stock)
        self.bloom(project)["values"]["intensity"] = 0.7
        camera = next(event for track in project["tracks"] if track["kind"] == "camera" for event in track["events"]
                      if "keyframes" in event["editableValues"])
        for point in camera["values"]["keyframes"][:30]:
            point["fov"] = point["fov"] + 2
        job, _, calls = self.job(self.request(project, title="값 편집 곡"))
        self.assertIn("stop", calls)
        song = mv_studio_live.describe_mv_song(self.root, region="gl", live_id=job.song()["song"]["liveId"])
        self.assertEqual(song["platforms"], {"android": "custom", "ios": "custom"})
        registered = register._registered_timelines(self.root, song)
        self.assertEqual(sorted(registered), ["android", "ios"])
        # Open it from the songs list: the registered Android timeline, imported again.
        reopened = self.imported(registered["android"], {
            "kind": "game", "region": "gl", "platform": "android", "liveId": song["liveId"], "assetId": song["assetId"],
            "mvOnly": True, "registered": True, "registeredSong": opened_song(song)})
        self.assertEqual(self.bloom(reopened)["values"]["intensity"], struct.unpack("<f", struct.pack("<f", 0.7))[0])
        plan = register.plan(self.root, reopened)
        self.assertNotEqual(plan["timeline"]["fingerprints"], song["fingerprints"], "The values came back as float32")
        self.assertEqual((plan["target"], plan["timeline"]["keep"], plan["timeline"]["bake"]),
                         (song["liveId"], ["android", "ios"], []))
        update = {"mode": "update", "liveId": song["liveId"], "jacket": {"kind": "keep"}, "audio": {"kind": "keep"},
                  "platforms": RegisterJobTests.panel_platforms(plan), "title": "값 편집 곡"}
        exports = len(self.exports)
        job, summary, calls = self.job(self.request(reopened, **update))
        self.assertEqual(summary, register.NO_CHANGES)
        self.assertEqual(calls, ["begin_job", "finish_job:True"], "No stop and no start")
        self.assertEqual(len(self.exports), exports, "Kept without a bake")
        self.assertEqual((job.song()["changed"], job.song()["restart"]), (False, "none"))
        # The bloom value typed again as 0.7: the posted project no longer equals the registered
        # timeline's values, but its bake gives the registered bytes exactly (no tolerance).
        self.bloom(reopened)["values"]["intensity"] = 0.7
        plan = register.plan(self.root, reopened)
        self.assertEqual(plan["timeline"]["bake"], ["android", "ios"])
        job, summary, calls = self.job(self.request(reopened, **update))
        self.assertEqual(len(self.exports), exports + 2)
        self.assertEqual(summary, register.NO_CHANGES)
        self.assertEqual(calls, ["begin_job", "finish_job:True"], "No stop and no start")
        after = mv_studio_live.describe_mv_song(self.root, region="gl", live_id=song["liveId"])
        self.assertEqual((after["revision"], after["fingerprints"], after["platforms"]),
                         (song["revision"], song["fingerprints"], song["platforms"]))
        # The song removed: the opened project asks for a stock base, and with the song's own base it
        # is a mod of it whose timeline fits that base (no structure or base mismatch).
        review = register.remove_plan(self.root, region="gl", live_id=song["liveId"])
        controller = Controller()
        self.serverctl.register_controller(controller)
        try:
            register.run_remove(FakeJob(), self.root, register.validate_remove(
                {"region": "gl", "liveId": song["liveId"], "reviewToken": review["reviewToken"]}))
        finally:
            self.serverctl.register_controller(None)
        self.assertEqual(controller.calls, ["begin_job", "stop", "start", "finish", "finish_job:True"])
        self.assertEqual(register.plan(self.root, reopened)["blocked"], [{"message": register.SOURCE_REMOVED}])
        plan = register.plan(self.root, reopened, template={"region": "gl", "liveId": 21, "assetId": 2101})
        self.assertEqual((plan["timeline"]["kind"], plan["projectPlatform"], plan["blocked"], plan["timeline"]["bake"]),
                         ("mod", "android", [], ["android", "ios"]))


if __name__ == "__main__":
    unittest.main()
