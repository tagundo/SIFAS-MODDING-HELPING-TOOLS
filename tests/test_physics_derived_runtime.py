"""Saved grafts keep typed caller flags without becoming original game imports."""
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

from test_transplant_physics_graph import donor_chain
from webtools.core import model_edits, viewer_mod_sources, viewer_physics, viewer_physics_runtime as runtime


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class DerivedPhysicsRuntimeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.cache = self.root / "game-models"
        self.cache.mkdir()
        database = self.root / "assets/db/gl/masterdata.db"
        database.parent.mkdir(parents=True)
        with sqlite3.connect(database) as db:
            db.execute("CREATE TABLE m_suit_custom3d (suit_master_id INTEGER, skirtsafe_disable INTEGER)")
            db.executemany("INSERT INTO m_suit_custom3d VALUES (?,?)", [(1, 1), (2, 0)])
        self.raw = donor_chain()
        self.wearer, self.donor, self.output = [self.root / name for name in ("wearer.unity", "donor.unity", "graft.unity")]
        for path in (self.wearer, self.donor, self.output):
            path.write_bytes(self.raw)
        self.originals = {str(self.wearer): (1, 101), str(self.donor): (2, 102)}
        # Original identity verification has its own importer/catalog tests.
        # Here it accepts only the two pinned, unchanged original files; output
        # copies deliberately never match, even when they contain equal bytes.
        def original_bindings(context, repo_root, *, receipts):
            containers, sources = viewer_mod_sources._snapshots(context)
            found = []
            for source in sources:
                identity = self.originals.get(source["path"])
                if identity and source["sha256"] == sha(self.raw) and Path(source["path"]).read_bytes() == self.raw:
                    suit, owner = identity
                    found.append({"source": source["source"], "record": {"region": "gl", "suit_id": suit, "owner": owner}})
            return found
        patcher = mock.patch("webtools.core.viewer_mod_sources.game_context", side_effect=original_bindings)
        patcher.start(); self.addCleanup(patcher.stop)
        cache = mock.patch("webtools.core.viewer_mod_flow.cached_receipts", return_value=())
        cache.start(); self.addCleanup(cache.stop)
        self.origins = [
            {"componentId": "221", "serializedFile": 0, "source": "wearer", "sourceComponentId": "221", "sourceSerializedFile": 0},
            {"componentId": "252", "serializedFile": 0, "source": "donor", "sourceComponentId": "252", "sourceSerializedFile": 0},
        ]

    def context(self, path):
        raw = path.read_bytes()
        return {"containers": [{"path": str(path), "raw": raw, "sha256": sha(raw)}],
                "sources": [{"container": 0, "member": None, "raw": raw, "sha256": sha(raw)}]}

    def catalog(self, path):
        info = model_edits._inspect(path.read_bytes())
        bones = [{"sourceIndex": 0, "serializedFile": key[0], "transformId": str(key[1]), "node": index}
                 for index, key in enumerate(info["transforms"])]
        return viewer_physics.make_catalog(viewer_physics.inspect_info(info, 0, bones), viewer_physics.native_managers(info, 0, bones))

    def record(self, operation="part"):
        return runtime.record_transplant(str(self.output), wearer_context=self.context(self.wearer), wearer_source=0,
            donor_path=str(self.donor), donor_member=None, donor_sha256=sha(self.raw), operation=operation,
            component_origins=self.origins, repo_root=self.root, cache_root=self.cache)

    def describe(self, path=None):
        path = path or self.output
        return runtime.describe(self.context(path), self.catalog(path), repo_root=self.root, cache_root=self.cache)

    def test_mixed_manager_restores_each_verified_component_after_restart(self):
        self.record()
        runtime._FACTS.clear()
        with mock.patch.object(viewer_mod_sources, "_REGISTRY", {}):
            result = self.describe()
        self.assertTrue(result["sources"][0]["derived"])
        self.assertTrue(result["sources"][0]["known"])
        self.assertIsNone(result["sources"][0]["skirtsafeDisable"], "A hybrid is not assigned one guessed costume flag")
        self.assertEqual(result["skirtsafeDisableByComponent"], {"0:0:221": True, "0:0:252": False})
        self.assertEqual(result["derivedOwner"]["character_id"], 101, "The target owner is retained separately")
        self.assertEqual(viewer_mod_sources.game_context(self.context(self.output), self.root, receipts=()), [])
        self.assertEqual(self.output.read_bytes(), self.raw)
        self.assertEqual(self.wearer.read_bytes(), self.raw)
        self.assertEqual(self.donor.read_bytes(), self.raw)

    def test_regular_save_retains_runtime_and_target_without_counterpart_identity(self):
        self.record()
        edited = self.root / "saved.unity"
        edited.write_bytes(self.raw)
        result = runtime.inherit_export(self.context(self.output), [str(edited)], repo_root=self.root, cache_root=self.cache)
        self.assertEqual(result, {"derivedOutputs": 1})
        runtime._FACTS.clear()
        self.assertEqual(self.describe(edited)["skirtsafeDisableByComponent"], {"0:0:221": True, "0:0:252": False})
        owner = runtime.owner_for_context(self.context(edited), repo_root=self.root, cache_root=self.cache)
        self.assertEqual(owner["operations"], ["part", "edit"])
        self.assertEqual(owner["character_id"], 101)
        self.assertTrue(owner["derived"])
        self.assertEqual(viewer_mod_sources.game_context(self.context(edited), self.root, receipts=()), [])

    def test_changed_output_and_unrecorded_equal_copy_stay_unknown(self):
        self.record()
        unrecorded = self.root / "copy.unity"
        unrecorded.write_bytes(self.raw)
        self.assertFalse(self.describe(unrecorded)["sources"][0]["known"])
        self.output.write_bytes(self.raw + b"changed")
        self.assertFalse(self.describe()["sources"][0]["known"])

    def test_repeated_saves_do_not_exhaust_the_derived_parent_depth(self):
        self.record()
        previous = self.output
        for index in range(24):
            saved = self.root / ("saved-" + str(index) + ".unity")
            saved.write_bytes(self.raw)
            runtime.inherit_export(self.context(previous), [str(saved)], repo_root=self.root, cache_root=self.cache)
            previous = saved
        self.assertTrue(self.describe(previous)["sources"][0]["known"])
        owner = runtime.owner_for_context(self.context(previous), repo_root=self.root, cache_root=self.cache)
        self.assertEqual(owner["operations"], ["part", "edit"])
        receipt = json.loads(runtime._receipt_path(self.cache, previous).read_text())
        self.assertEqual(len(receipt["sources"][0]["parents"]), 2)

    def test_changed_parent_and_receipt_replay_do_not_authenticate_output(self):
        self.record()
        other = self.root / "other.unity"
        other.write_bytes(self.raw)
        receipt = runtime._receipt_path(self.cache, self.output)
        replay = runtime._receipt_path(self.cache, other)
        replay.write_bytes(receipt.read_bytes())
        self.assertFalse(self.describe(other)["sources"][0]["known"])
        self.donor.write_bytes(self.raw + b"changed")
        self.assertFalse(self.describe()["sources"][0]["known"])

    def test_unknown_or_malformed_provenance_does_not_block_edit_save(self):
        self.record()
        runtime._receipt_path(self.cache, self.output).write_text("[]")
        self.assertFalse(self.describe()["sources"][0]["known"])
        edited = self.root / "edited.unity"
        edited.write_bytes(self.raw)
        self.assertEqual(runtime.inherit_export(self.context(self.output), [str(edited)],
            repo_root=self.root, cache_root=self.cache), {"derivedOutputs": 0})

    def test_unresolved_typed_component_never_inherits_a_default_flag(self):
        self.record()
        receipt = runtime._receipt_path(self.cache, self.output)
        value = json.loads(receipt.read_text())
        value["sources"][0]["components"][1]["sourceId"] = "0:99999"
        receipt.write_text(json.dumps(value))
        result = self.describe()
        self.assertFalse(result["sources"][0]["known"])
        self.assertEqual(result["skirtsafeDisableByComponent"], {"0:0:221": True})

    def test_changed_donor_snapshot_is_rejected_before_receipt_publication(self):
        self.donor.write_bytes(self.raw + b"changed")
        with self.assertRaisesRegex(ValueError, "donor changed"):
            self.record()
        self.assertFalse(runtime._receipt_path(self.cache, self.output).exists())

    def test_cyclic_receipt_is_bounded_and_does_not_fake_complete_mapping(self):
        self.record()
        receipt = runtime._receipt_path(self.cache, self.output)
        value = json.loads(receipt.read_text())
        value["sources"][0]["parents"][0] = runtime._source_proofs(self.context(self.output))[0]
        receipt.write_text(json.dumps(value))
        result = self.describe()
        self.assertFalse(result["sources"][0]["known"])
        self.assertNotIn("derivedOwner", result)


if __name__ == "__main__":
    unittest.main()
