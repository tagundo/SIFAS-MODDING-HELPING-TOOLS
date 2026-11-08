"""ZIP replacement keeps reload checks without inflating superseded members."""
import copy
import hashlib
import io
from pathlib import Path
import random
import secrets
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from webtools.core import model_edits as edits, model_viewer, viewer_archive
from webtools.core import viewer_mod_pair_edits as paired


def legacy_replace_zip(raw, replacements):
    """Independent pre-optimization writer/reload behavior for valid archives."""
    destination = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(raw)) as incoming, zipfile.ZipFile(destination, "w") as outgoing:
        outgoing.comment = incoming.comment
        pending = dict(replacements)
        for entry in incoming.infolist():
            outgoing.writestr(copy.copy(entry), pending.pop(entry.filename, incoming.read(entry)))
        if pending:
            raise ValueError("missing replacement")
    value = destination.getvalue()
    with zipfile.ZipFile(io.BytesIO(raw)) as incoming, zipfile.ZipFile(io.BytesIO(value)) as checked:
        if incoming.namelist() != checked.namelist() or incoming.comment != checked.comment:
            raise ValueError("archive structure changed")
        for entry in incoming.infolist():
            expected = replacements.get(entry.filename, incoming.read(entry))
            if checked.read(entry.filename) != expected:
                raise ValueError("replacement changed")
    return value


def archive_bytes(entries):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.comment = b"preserve the original archive comment"
        for index, (name, raw) in enumerate(entries):
            entry = zipfile.ZipInfo(name, (2026, 1, 2, 3, 4, index * 2))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.comment = b"entry metadata"
            entry.extra = b"\xca\xfe\x02\x00XY"
            entry.external_attr = 0o100640 << 16
            archive.writestr(entry, raw)
    return output.getvalue()


class ZipReplacementTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="zip-replacement-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.old_body = random.Random(20261108).randbytes(1024 * 1024)
        self.raw = archive_bytes([
            ("android.unity", self.old_body), ("ios.unity", b"native iOS original"),
            ("texture.png", b"unchanged texture bytes"), ("modinstall.txt", b"keep manifest"),
        ])
        self.source = self.root / "source.zip"
        self.source.write_bytes(self.raw)
        self.destination = self.root / "changed.zip"

    def test_complete_archive_matches_old_writer_and_preserves_metadata(self):
        replacements = {"android.unity": b"edited Android", "ios.unity": b"edited iOS"}
        expected = legacy_replace_zip(self.raw, replacements)
        result = paired._replace_zip(self.source, self.destination, replacements)
        self.assertEqual(result, hashlib.sha256(self.raw).hexdigest())
        self.assertEqual(self.destination.read_bytes(), expected)
        self.assertEqual(self.source.read_bytes(), self.raw)
        self.assertEqual(replacements, {"android.unity": b"edited Android", "ios.unity": b"edited iOS"})
        with zipfile.ZipFile(io.BytesIO(self.raw)) as old, zipfile.ZipFile(self.destination) as new:
            self.assertEqual(old.namelist(), new.namelist())
            self.assertEqual(old.comment, new.comment)
            for old_entry, new_entry in zip(old.infolist(), new.infolist()):
                for field in ("filename", "date_time", "comment", "extra", "external_attr", "compress_type"):
                    self.assertEqual(getattr(old_entry, field), getattr(new_entry, field))

    def test_replaced_source_members_are_not_decompressed_but_every_output_is_checked(self):
        original_read = zipfile.ZipFile.read
        source_reads, completed_reads = [], []
        def read(archive, name, *args, **kwargs):
            member = name.filename if isinstance(name, zipfile.ZipInfo) else name
            if isinstance(archive.fp, io.BytesIO) and archive.fp.getvalue() == self.raw:
                source_reads.append(member)
                if member in {"android.unity", "ios.unity"}:
                    raise AssertionError("Superseded original member was unnecessarily decompressed")
            elif archive.filename == str(self.destination):
                completed_reads.append(member)
            return original_read(archive, name, *args, **kwargs)
        with patch.object(zipfile.ZipFile, "read", new=read):
            paired._replace_zip(self.source, self.destination,
                                {"android.unity": b"new Android", "ios.unity": b"new iOS"})
        self.assertCountEqual(source_reads, ["texture.png", "modinstall.txt"] * 2)
        self.assertEqual(completed_reads, ["android.unity", "ios.unity", "texture.png", "modinstall.txt"])

    def test_output_reload_still_rejects_corrupt_replaced_and_unchanged_members(self):
        original_write = zipfile.ZipFile.writestr
        for corrupt in ("android.unity", "texture.png"):
            with self.subTest(corrupt=corrupt):
                def write(archive, entry, value, *args, **kwargs):
                    name = entry.filename if isinstance(entry, zipfile.ZipInfo) else entry
                    if archive.filename == str(self.destination) and name == corrupt:
                        value += b"injected corruption"
                    return original_write(archive, entry, value, *args, **kwargs)
                with patch.object(zipfile.ZipFile, "writestr", new=write):
                    with self.assertRaisesRegex(ValueError, "completed-member reload"):
                        paired._replace_zip(self.source, self.destination, {"android.unity": b"edited"})
                self.assertEqual(self.source.read_bytes(), self.raw)

    def test_missing_declared_replacement_still_fails(self):
        with self.assertRaisesRegex(ValueError, "missing a declared variant"):
            paired._replace_zip(self.source, self.destination, {"not-in-archive.unity": b"edited"})
        self.assertEqual(self.source.read_bytes(), self.raw)

    def test_no_replacements_preserves_the_old_full_archive_behavior(self):
        paired._replace_zip(self.source, self.destination, {})
        self.assertEqual(self.destination.read_bytes(), legacy_replace_zip(self.raw, {}))
        self.assertEqual(self.source.read_bytes(), self.raw)


class SerializedZipExportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="serialized-zip-replacement-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.model = (Path(__file__).parent / "fixtures/viewer_persistence.unity").read_bytes()
        self.raw = archive_bytes([
            ("primary.unity", self.model), ("unmasked.unity", self.model),
            ("modinstall.txt", b"costume_file='primary.unity'\nrina_unmask_costume_file='unmasked.unity'\n"),
            ("untouched.bin", b"preserve these bytes"),
        ])
        self.source = self.root / "rina.zip"
        self.source.write_bytes(self.raw)
        self.token = secrets.token_hex(16)
        with edits._LOCK:
            edits._SESSIONS.clear()
        with viewer_archive.expand_inputs([str(self.source)], self.root / "cache",
                variant_choices={str(self.source): "unmasked"}) as expanded:
            prepared = model_viewer.prepare(expanded.paths, rigged=True,
                face_context={"enabled": False, "allow_download": False})
            metadata = edits.register_session(self.token, expanded.paths, prepared["rig"],
                originals=[str(self.source)], origins=expanded.origins,
                archive_members=expanded.archive_members, variants={str(self.source): "unmasked"})
        node = next(row for row in metadata["nodes"] if row["name"] == "LeftUpLeg")
        self.state = {"version": 1, "savedSettingsEnabled": True,
            "edits": [{"node": node["node"], "method": "mesh", "scale": [1.6, 1.2, 1.]}]}

    def test_actual_mesh_export_matches_legacy_zip_and_skips_replaced_original_read(self):
        original_read = zipfile.ZipFile.read
        original_reads = []
        def read(archive, name, *args, **kwargs):
            member = name.filename if isinstance(name, zipfile.ZipInfo) else name
            if isinstance(archive.fp, io.BytesIO) and archive.fp.getvalue() == self.raw:
                original_reads.append(member)
                if member == "unmasked.unity":
                    raise AssertionError("Edited original was unnecessarily decompressed during saving")
            return original_read(archive, name, *args, **kwargs)
        with patch.object(zipfile.ZipFile, "read", new=read):
            result = edits.export(self.token, self.state, self.root / "exports")
        saved_path = Path(result["preview_paths"][0])
        with zipfile.ZipFile(saved_path) as saved:
            edited = saved.read("unmasked.unity")
            self.assertNotEqual(edited, self.model)
        self.assertEqual(saved_path.read_bytes(), legacy_replace_zip(self.raw, {"unmasked.unity": edited}))
        self.assertCountEqual(original_reads, ["primary.unity", "modinstall.txt", "untouched.bin"] * 2)
        self.assertEqual(result["summary"][0]["meshes"][0]["vertices"], 6)
        self.assertEqual(self.source.read_bytes(), self.raw)
        self.assertEqual(result["preview_variants"], {"0": "unmasked"})
        self.assertEqual(Path(result["original_paths"][0]).read_bytes(), self.raw)

    def test_stale_original_zip_still_prevents_publication(self):
        destination = self.root / "blocked"
        self.source.write_bytes(self.raw + b"changed after opening")
        with self.assertRaisesRegex(edits.ModelEditError, "changed after opening"):
            edits.export(self.token, self.state, destination)
        self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
