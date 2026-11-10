"""Trusted app-root aliases survive grafting without authorizing selected links."""
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from test_transplant_physics_graph import as_bundle, donor_chain
from webtools.core import (model_edits, model_viewer, viewer_mod_sources,
                           viewer_physics, viewer_physics_runtime, viewer_transplants)
from webtools.jobs import Job


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class ViewerTransplantPathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = as_bundle(donor_chain())

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        data = self.root / "data-data"
        data.mkdir()
        alias = self.root / "data-user-0"
        alias.symlink_to(data, target_is_directory=True)
        self.files = data / "com.tagundo.elichika/files"
        self.files.mkdir(parents=True)
        self.alias_files = alias / "com.tagundo.elichika/files"
        environment = patch.dict(os.environ, {"SUKUSTA_DIR": str(self.root / "library")})
        environment.start()
        self.addCleanup(environment.stop)
        roots = viewer_transplants.filebrowser.allowed_roots()
        roots["home"] = str(self.alias_files)
        configured_home = patch.object(viewer_transplants.filebrowser, "allowed_roots", return_value=roots)
        configured_home.start()
        self.addCleanup(configured_home.stop)
        self.wearer = self.files / "wearer.unity"
        self.donor = self.files / "donor.unity"
        self.wearer.write_bytes(self.raw)
        self.donor.write_bytes(self.raw)
        rig = model_viewer.prepare([str(self.alias_files / self.wearer.name)], rigged=True,
            face_context={"enabled": False, "allow_download": False})["rig"]
        self.token = secrets.token_hex(16)
        self.metadata = model_edits.register_session(self.token,
            [str(self.alias_files / self.wearer.name)], rig)
        self.cache = self.root / "game-models"
        self.cache.mkdir()

    def request(self, **changes):
        value = {"token": self.token, "state": {"version": 1, "edits": []},
            "donor": str(self.alias_files / self.donor.name), "variant": "primary",
            "operation": "costume", "partRoot": "", "cutLow": .5, "cutHigh": .92,
            "region": "lower", "donorSha256": sha(self.raw)}
        value.update(changes)
        return value

    @staticmethod
    def context(path):
        raw = path.read_bytes()
        return {"containers": [{"path": str(path), "raw": raw, "sha256": sha(raw)}],
                "sources": [{"container": 0, "member": None, "raw": raw, "sha256": sha(raw)}]}

    def graft(self, request):
        job = Job(secrets.token_hex(6), "viewer_transplant")
        viewer_transplants.run_transplant(job, request, output_root=self.root / "output",
            cache_root=self.root / "viewer-cache", repo_root=self.root, physics_cache_root=self.cache)
        self.assertEqual(len(job.output_paths()), 1)
        return Path(job.output_paths()[0])

    def test_configured_os_alias_inspects_selects_grafts_and_reloads_typed_physics(self):
        inspected = viewer_transplants.inspect_donor(str(self.alias_files / self.donor.name),
            cache_root=self.root / "viewer-cache")
        self.assertEqual(inspected["sha256"], sha(self.raw))
        self.assertTrue(inspected["parts"])
        request = viewer_transplants.validate_request(self.request())
        self.assertEqual(request["donor"], str(self.donor))
        self.assertEqual(request["donorRaw"], self.raw)
        # Neutral fixtures do not become official game assets. Mock only the
        # independently tested importer boundary, pinned to the two real paths
        # and their unchanged bytes; all graft/receipt/catalogue IO stays real.
        database = self.root / "assets/db/gl/masterdata.db"
        database.parent.mkdir(parents=True)
        with sqlite3.connect(database) as db:
            db.execute("CREATE TABLE m_suit_custom3d (suit_master_id INTEGER, skirtsafe_disable INTEGER)")
            db.executemany("INSERT INTO m_suit_custom3d VALUES (?, ?)", [(1, 1), (2, 0)])
        originals = {str(self.wearer): (1, 101), str(self.donor): (2, 102)}
        def originals_only(context, repo_root, *, receipts):
            _, entries = viewer_mod_sources._snapshots(context)
            return [{"source": entry["source"], "record": {"region": "gl",
                "suit_id": originals[entry["path"]][0], "owner": originals[entry["path"]][1]}}
                for entry in entries if entry["path"] in originals
                and entry["sha256"] == sha(self.raw) and Path(entry["path"]).read_bytes() == self.raw]
        with patch.object(viewer_mod_sources, "game_context", side_effect=originals_only), \
                patch("webtools.core.viewer_mod_flow.cached_receipts", return_value=()):
            output = self.graft(request)
            receipt = json.loads(viewer_physics_runtime._receipt_path(self.cache, output).read_text())
            self.assertEqual(receipt["sha256"], sha(output.read_bytes()))
            self.assertEqual(receipt["sources"][0]["parents"][1]["path"], str(self.donor))
            viewer_physics_runtime._FACTS.clear()
            info = model_edits._inspect(output.read_bytes())
            bones = [{"sourceIndex": 0, "serializedFile": key[0], "transformId": str(key[1]), "node": index}
                for index, key in enumerate(info["transforms"])]
            catalog = viewer_physics.make_catalog(viewer_physics.inspect_info(info, 0, bones),
                viewer_physics.native_managers(info, 0, bones))
            self.assertTrue(catalog["native"]["available"], catalog["native"])
            result = viewer_physics_runtime.describe(self.context(output), catalog,
                repo_root=self.root, cache_root=self.cache)
            self.assertTrue(result["sources"][0]["known"], result)
            self.assertTrue(result["sources"][0]["derived"])
            self.assertTrue(result["skirtsafeDisableByComponent"])
            self.assertEqual(result["derivedOwner"]["character_id"], 101)
        self.assertEqual(self.wearer.read_bytes(), self.raw)
        self.assertEqual(self.donor.read_bytes(), self.raw)

    def test_leaf_and_interior_links_below_trusted_root_are_rejected(self):
        leaf = self.files / "linked.unity"
        leaf.symlink_to(self.donor)
        real_directory = self.files / "models"
        real_directory.mkdir()
        (real_directory / self.donor.name).write_bytes(self.raw)
        nested = self.files / "linked-models"
        nested.symlink_to(real_directory, target_is_directory=True)
        for name in (leaf.relative_to(self.files), nested.relative_to(self.files) / self.donor.name):
            with self.subTest(path=str(name)), self.assertRaisesRegex(ValueError, "symbolic link"):
                viewer_transplants.validate_request(self.request(donor=str(self.alias_files / name)))

        # Derived file-picker start folders are not new trust boundaries.
        library = self.root / "library"
        library.mkdir()
        (library / "extracted").symlink_to(self.files, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symbolic link"):
            viewer_transplants.validate_request(self.request(donor=str(library / "extracted/donor.unity")))

    def test_source_bound_partial_face_selection_keeps_the_checked_canonical_donor(self):
        inspected = viewer_transplants.inspect_donor(str(self.alias_files / self.donor.name),
            cache_root=self.root / "viewer-cache")
        geometry = inspected["geometry"]
        request = viewer_transplants.validate_request(self.request(operation="part",
            partSelectionMode="triangles", partRoots=[], includeDescendants=True,
            triangleIndices=[0], donorRenderer=geometry["renderer"], donorMesh=geometry["mesh"],
            donorSelectionFingerprint=inspected["selectionFingerprint"]))
        self.assertEqual(request["triangleIndices"], [0])
        self.assertEqual(request["donor"], str(self.donor))
        output = self.graft(request)
        receipt = json.loads(viewer_physics_runtime._receipt_path(self.cache, output).read_text())
        self.assertEqual(receipt["sources"][0]["operation"], "part")
        self.assertEqual(receipt["sources"][0]["parents"][1]["path"], str(self.donor))
        self.assertEqual(receipt["sha256"], sha(output.read_bytes()))
        self.assertEqual(self.wearer.read_bytes(), self.raw)
        self.assertEqual(self.donor.read_bytes(), self.raw)

    def test_external_alias_cannot_become_a_trusted_root(self):
        alias = self.root / "unconfigured-alias"
        alias.symlink_to(self.files, target_is_directory=True)
        with self.assertRaises(PermissionError):
            viewer_transplants.validate_request(self.request(donor=str(alias / self.donor.name)))

    def test_changed_donor_after_validation_rolls_back_output_and_receipt(self):
        request = viewer_transplants.validate_request(self.request())
        self.donor.write_bytes(self.raw + b"changed after selection")
        with self.assertRaisesRegex(ValueError, "donor changed"):
            self.graft(request)
        self.assertEqual(list((self.root / "output").glob("transplant-*")), [])
        self.assertEqual(list((self.cache / "viewer-derived-physics").glob("*.json")), [])
        self.assertEqual(self.wearer.read_bytes(), self.raw)

    def test_changed_selection_hash_and_unchanged_strict_reader_reject_links(self):
        with self.assertRaisesRegex(ValueError, "donor changed"):
            viewer_transplants.validate_request(self.request(donorSha256="0" * 64))
        with self.assertRaisesRegex(ValueError, "symbolic link"):
            viewer_mod_sources._read(str(self.alias_files / self.donor.name))

    def test_native_runtime_root_without_home_can_publish_a_graft(self):
        roots = {"sukusta": str(self.root / "library"), "runtime": str(self.files)}
        with patch.object(viewer_transplants.filebrowser, "allowed_roots", return_value=roots):
            inspected = viewer_transplants.inspect_donor(str(self.donor), cache_root=self.root / "viewer-cache")
            self.assertEqual(inspected["sha256"], sha(self.raw))
            request = viewer_transplants.validate_request(self.request(donor=str(self.donor)))
            output = self.graft(request)
            receipt = json.loads(viewer_physics_runtime._receipt_path(self.cache, output).read_text())
            self.assertEqual(receipt["sources"][0]["parents"][1]["path"], str(self.donor))

    def test_native_selected_file_root_does_not_authorize_its_parent_or_sibling(self):
        selected = self.root / "outside-home/selected.unity"
        selected.parent.mkdir()
        selected.write_bytes(self.raw)
        sibling = selected.with_name("unselected.unity")
        sibling.write_bytes(self.raw)
        roots = {"runtime": str(self.files), "selected_1": str(selected)}
        with patch.object(viewer_transplants.filebrowser, "allowed_roots", return_value=roots), \
                patch.object(viewer_transplants.filebrowser, "is_within_allowed",
                             side_effect=lambda path: Path(path) == selected) as authority:
            request = viewer_transplants.validate_request(self.request(donor=str(selected)))
            self.assertEqual(request["donor"], str(selected))
            authority.assert_called_with(selected)
            with self.assertRaises(PermissionError):
                viewer_transplants.validate_request(self.request(donor=str(sibling)))
            self.assertNotIn(sibling, [call.args[0] for call in authority.call_args_list])
        with patch.object(viewer_transplants.filebrowser, "allowed_roots", return_value=roots), \
                patch.object(viewer_transplants.filebrowser, "is_within_allowed", return_value=False):
            with self.assertRaises(PermissionError):
                viewer_transplants.validate_request(self.request(donor=str(selected)))

    def test_native_selected_directory_root_rejects_interior_and_leaf_links(self):
        directory = self.root / "selected-external-folder"
        directory.mkdir()
        selected = directory / "donor.unity"
        selected.write_bytes(self.raw)
        leaf = directory / "linked.unity"
        leaf.symlink_to(selected)
        nested = directory / "linked-folder"
        nested.symlink_to(self.files, target_is_directory=True)
        roots = {"runtime": str(self.files), "selected_1": str(directory)}
        with patch.object(viewer_transplants.filebrowser, "allowed_roots", return_value=roots):
            request = viewer_transplants.validate_request(self.request(donor=str(selected)))
            self.assertEqual(request["donor"], str(selected))
            for path in (leaf, nested / self.donor.name):
                with self.subTest(path=str(path)), self.assertRaisesRegex(ValueError, "symbolic link"):
                    viewer_transplants.validate_request(self.request(donor=str(path)))

    def test_canonical_native_root_accepts_only_verified_system_alias_prefix(self):
        roots = {"runtime": str(self.files)}
        known_alias = self.alias_files.parents[1]
        destination = self.files.parents[1]
        with patch.object(viewer_transplants, "_OS_PATH_ALIASES", ((str(known_alias), str(destination)),)), \
                patch.object(viewer_transplants.filebrowser, "allowed_roots", return_value=roots), \
                patch.object(viewer_transplants.filebrowser, "is_within_allowed",
                             side_effect=lambda path: Path(path).is_relative_to(self.files)) as authority:
            request = viewer_transplants.validate_request(self.request())
            self.assertEqual(request["donor"], str(self.donor))
            authority.assert_called_with(self.donor)
            other = self.root / "not-system-alias"
            other.symlink_to(destination, target_is_directory=True)
            with self.assertRaises(PermissionError):
                viewer_transplants.validate_request(self.request(donor=str(other / "com.tagundo.elichika/files/donor.unity")))
        with patch.object(viewer_transplants, "_OS_PATH_ALIASES", ((str(known_alias), str(self.root)),)), \
                patch.object(viewer_transplants.filebrowser, "allowed_roots", return_value=roots):
            with self.assertRaises(PermissionError):
                viewer_transplants.validate_request(self.request())


if __name__ == "__main__":
    unittest.main()
