"""One source-bound export for body, mesh and thumbnail/package channels."""
import ast
import base64
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import UnityPy
from PIL import Image

from generate_viewer_physics_fixture import fixture_bytes
from test_viewer_transplants import costume_fixture
from webtools.core import model_edits, model_viewer, viewer_mesh_tools as mesh, bundle_identity
from webtools.core import viewer_mod_flow as flow, viewer_thumbnails as thumbs
from webtools.core import viewer_physics, viewer_physics_runtime, viewer_transplants
from webtools.jobs import Job


class CombinedExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = UnityPy.load(fixture_bytes(native=True))
        for obj in env.objects:
            if obj.type.name == 'Texture2D':
                tree = obj.read_typetree(); tree['m_Name'] = 'ch0006_co0001_body'
                obj.save_typetree(tree)
        cls.raw = env.file.save()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.library = self.root / 'library'
        self.environment = patch.dict(os.environ, {'SUKUSTA_DIR': str(self.library)})
        self.environment.start(); self.addCleanup(self.environment.stop)
        jailed = patch('webtools.filebrowser.is_within_allowed', lambda value: Path(value).resolve().is_relative_to(self.root))
        jailed.start(); self.addCleanup(jailed.stop)
        roots = patch('webtools.filebrowser.allowed_roots', return_value={'home': str(self.root), 'sukusta': str(self.library)})
        roots.start(); self.addCleanup(roots.stop)
        self.addCleanup(thumbs._PLANS.clear)
        self.source = self.root / 'costume.unity'; self.source.write_bytes(self.raw)
        self.output = self.root / 'exports'; self.cache = self.library / 'extracted/game-models'
        self.runtime = self.root / 'runtime'; self.runtime.mkdir()
        self.token, self.metadata = self.open(self.source)
        self.identity = mesh.inspect(self.token)['meshes'][0]['mesh']
        self.empty = {'version': 1, 'savedSettingsEnabled': True, 'edits': []}

    def open(self, path):
        rig = model_viewer.prepare([str(path)], rigged=True,
            face_context={'enabled': False, 'allow_download': False})['rig']
        token = secrets.token_hex(16)
        return token, model_edits.register_session(token, [str(path)], rig)

    def mesh_state(self, **changes):
        return {'version': 1, 'meshes': [{'mesh': self.identity, **changes}]}

    def export(self, state, **options):
        return flow.export_current(self.token, state, self.output,
            repo_root=self.runtime, cache_root=self.cache, **options)

    def package(self, state, **options):
        return flow.create_package(self.token, state, output_root=self.output,
            repo_root=self.runtime, cache_root=self.cache, display_name='Combined edited costume',
            character_id=6, job=Job(secrets.token_hex(6), 'viewer_mod_package'), **options)

    def test_actual_graft_packages_without_a_dummy_body_edit(self):
        source, donor = self.root / 'wearer.unity', self.root / 'donor.unity'
        env = UnityPy.load(costume_fixture())
        for obj in env.objects:
            if obj.type.name == 'Texture2D':
                tree = obj.read_typetree(); tree['m_Name'] = 'ch0006_co0001_body'; obj.save_typetree(tree)
        raw = env.file.save(); source.write_bytes(raw); donor.write_bytes(raw)
        token, _ = self.open(source)
        request = viewer_transplants.validate_request({'token': token, 'state': self.empty,
            'donor': str(donor), 'variant': 'primary', 'operation': 'part', 'partRoot': 'LeftArm',
            'cutLow': .5, 'cutHigh': .92, 'region': 'lower'})
        job = Job(secrets.token_hex(6), 'viewer_transplant')
        viewer_transplants.run_transplant(job, request, output_root=self.output,
            cache_root=self.root / '.viewer-cache', physics_cache_root=self.cache)
        graft = Path(job.output_paths()[0]); graft_raw = graft.read_bytes()
        self.token, _ = self.open(graft)
        result = self.package(self.empty)
        self.assertEqual(result['recipe']['state']['edits'], [])
        self.assertEqual(Path(result['preview_paths'][0]).read_bytes(), graft_raw)
        self.assertEqual(Path(result['original_paths'][0]).read_bytes(), graft_raw)
        with zipfile.ZipFile(result['mod_package']['package_path']) as archive:
            fields = {node.targets[0].id: ast.literal_eval(node.value)
                      for node in ast.parse(archive.read('modinstall.txt').decode()).body}
            self.assertEqual(archive.read(fields['costume_file']), graft_raw)
        self.assertEqual(source.read_bytes(), raw); self.assertEqual(donor.read_bytes(), raw)
        self.assertEqual(graft.read_bytes(), graft_raw)

    def test_mesh_body_physics_and_outline_share_one_real_serialized_export(self):
        breast = next(row for row in self.metadata['nodes'] if row['name'] == 'BreastSize')
        bone = next(row for row in self.metadata['physics']['components'] if row['kind'] == 'bone')
        outline = self.metadata['outlines']['meshes'][0]['id']
        body = dict(self.empty, edits=[{'node': breast['node'], 'method': 'node', 'scale': [1.2, 1.3, 1.1]}],
            physics=[{'id': bone['id'], 'values': {**bone['values'], 'dragForce': .4}}],
            outlines=[{'id': outline, 'factor': .5}])
        operations = self.mesh_state(deleteFaces=[0], positions=[{'vertex': 0, 'position': [.2, .3, .4]}],
            weights=[{'vertex': 0, 'influences': [[0, .25], [1, .75]]}])
        result = self.export(body, mesh_state=operations)
        self.assertEqual(result['recipe']['state'], operations)
        self.assertEqual(result['recipe']['bodyState'], model_edits.validate_state(self.token, body))
        self.assertEqual(json.loads(Path(result['recipe_path']).read_text()), result['recipe'])
        raw = Path(result['preview_paths'][0]).read_bytes(); info = model_edits._inspect(raw)
        rows = viewer_physics.inspect_info(info, 0, [])
        self.assertAlmostEqual(next(row for row in rows if row['id'] == bone['id'])['values']['dragForce'], .4, places=6)
        target = next(key for key, value in info['names'].items() if value == 'BreastSize')
        for actual, expected in zip(info['effective'][target]['scale'], [1.2, 1.3, 1.1]):
            self.assertAlmostEqual(actual, expected, places=6)
        _, records = mesh._mesh_records(raw, 0); record = records[0]
        self.assertEqual(sum(part['indexCount'] for part in record[2]['m_SubMeshes']), 9)
        positions, _, weights, indices = mesh._arrays(record[1], record[2])
        for actual, expected in zip(positions[0], [.2, .3, .4]): self.assertAlmostEqual(actual, expected, places=6)
        influences = {int(index): float(weight) for index, weight in zip(indices[0], weights[0]) if weight > 0}
        self.assertEqual(influences, {0: .25, 1: .75})
        original = model_edits._inspect(self.raw)
        for key, obj in original['objects'].items():
            if obj.type.name == 'Texture2D': self.assertEqual(info['objects'][key].get_raw_data(), obj.get_raw_data())
        self.assertEqual(self.source.read_bytes(), self.raw)
        self.assertEqual(Path(result['original_paths'][0]).read_bytes(), self.raw)
        self.assertIn('metadata', result); self.assertIn('derived_runtime', result)

    def test_viewer_thumbnail_export_and_receipt_bind_the_actual_mesh_channel(self):
        operations = self.mesh_state(deleteFaces=[0])
        params = {'kind': 'viewer', 'token': self.token, 'state': self.empty, 'character_id': 6,
            'counterpart_path': None, 'selected_variant': None, 'mesh_state': operations}
        plan = thumbs.plan(params)
        item = thumbs._PLANS[plan['token']]['items'][0]
        _, records = mesh._mesh_records(Path(item['paths'][0]).read_bytes(), 0)
        self.assertEqual(sum(part['indexCount'] for part in records[0][2]['m_SubMeshes']), 9)
        image = Image.new('RGBA', (256, 256), (22, 55, 88, 255)); stream = io.BytesIO(); image.save(stream, format='PNG'); png = stream.getvalue()
        thumbs.store({'token': plan['token'], 'item_id': plan['items'][0]['id'], 'cache_key': plan['items'][0]['cacheKey'],
            'profile_digest': plan['profileDigest'], 'png': 'data:image/png;base64,' + base64.b64encode(png).decode(),
            'render': {'quality': {'enabled': True, 'ready': True}, 'subjectPixels': 128, 'triangles': 3}})
        result = self.package(self.empty, mesh_state=operations, thumbnail_token=plan['token'])
        self.assertEqual(result['mod_package']['thumbnail']['sha256'], hashlib.sha256(png).hexdigest())
        changed = self.mesh_state(deleteFaces=[1])
        with self.assertRaisesRegex(ValueError, 'changed'):
            thumbs.for_viewer_package(plan['token'], self.token, self.empty, 6, None, None, mesh_state=changed)
        with self.assertRaisesRegex(ValueError, 'changed'):
            thumbs.for_viewer_package(plan['token'], self.token, self.empty, 6, None, None)
        self.assertEqual(self.source.read_bytes(), self.raw)

    def test_empty_mesh_channel_preserves_the_legacy_thumbnail_binding(self):
        a, _, _ = thumbs._viewer_binding(self.token, self.empty, 6, None, None)
        b, _, _ = thumbs._viewer_binding(self.token, self.empty, 6, None, None, {'version': 1, 'meshes': []})
        self.assertEqual(a, b); self.assertNotIn('mesh_state', a)
        for value in ({'version': True, 'meshes': []}, {'version': 1, 'meshes': [], 'extra': 1},
                      {'version': 1, 'meshes': [{'value': float('nan')}]}):
            with self.subTest(value=value), self.assertRaises(ValueError): flow.normalize_mesh_state(value)

    def test_combined_recipe_restores_both_channels_from_preserved_originals(self):
        node = next(row for row in self.metadata['nodes'] if row['name'] == 'BreastSize')
        for body in (self.empty, dict(self.empty, edits=[{'node': node['node'], 'method': 'node', 'scale': [1.2, 1.3, 1.1]}])):
            with self.subTest(body_empty=not body['edits']):
                operations = self.mesh_state(deleteFaces=[0], positions=[{'vertex': 0, 'position': [.2, .3, .4]}])
                first = self.export(body, mesh_state=operations)
                token, _ = self.open(Path(first['original_paths'][0]))
                restored = flow.restore_current(token, json.loads(Path(first['recipe_path']).read_text()))
                self.assertEqual(restored['mesh_state'], operations)
                second = flow.export_current(token, restored['state'], self.output, mesh_state=restored['mesh_state'],
                    repo_root=self.runtime, cache_root=self.cache)
                self.assertEqual(Path(first['preview_paths'][0]).read_bytes(), Path(second['preview_paths'][0]).read_bytes())
        self.assertEqual(self.source.read_bytes(), self.raw)

    def test_combined_restore_rejects_forged_source_member_mesh_and_ranges(self):
        output = self.export(self.empty, mesh_state=self.mesh_state(deleteFaces=[0]))
        recipe = output['recipe']
        mutations = [lambda value: value['sources'].__setitem__(0, '0' * 64),
            lambda value: value['bodyRecipe']['sources'][0].__setitem__('member', 'different.unity'),
            lambda value: value['state']['meshes'][0]['mesh'].__setitem__('id', '999999'),
            lambda value: value['state']['meshes'][0].__setitem__('positions', [{'vertex': 999999, 'position': [0, 0, 0]}]),
            lambda value: value['bodyState'].__setitem__('savedSettingsEnabled', False)]
        for change in mutations:
            with self.subTest(change=change):
                forged = copy.deepcopy(recipe); change(forged)
                with self.assertRaises(ValueError): flow.restore_current(self.token, forged)
        self.assertEqual(self.source.read_bytes(), self.raw)

    def face_session(self, member, *, dependency=False, body_member=None):
        body = UnityPy.load(costume_fixture()); face = UnityPy.load(costume_fixture())
        for environment, name in ((body, f'ch{body_member if body_member is not None else member:04d}_co0001_body'), (face, f'ch{member:04d}_face')):
            for obj in environment.objects:
                if obj.type.name == 'Texture2D':
                    tree = obj.read_typetree(); tree['m_Name'] = name; obj.save_typetree(tree)
                if obj.type.name == 'AssetBundle':
                    tree = obj.read_typetree()
                    if environment is face:
                        tree['m_Name'] = tree['m_AssetBundleName'] = f'ch{member:04d}_facedynamic.prefab.unity3d'
                    elif dependency:
                        tree['m_Dependencies'] = [f'ch{member:04d}_facedynamic.prefab.unity3d']
                    obj.save_typetree(tree)
                if environment is face and obj.type.name == 'Mesh':
                    tree = obj.read_typetree(); tree['m_Name'] = 'Mouth'; obj.save_typetree(tree)
        body_raw, face_raw = body.file.save(), face.file.save()
        self.source.write_bytes(body_raw)
        path = self.root / f'member-{member}-face.unity'; path.write_bytes(face_raw)
        rig = model_viewer.prepare([str(self.source), str(path)], rigged=True,
            face_context={'enabled': False, 'allow_download': False})['rig']
        self.token = secrets.token_hex(16)
        # A neutral trusted-companion boundary, not a claim of original game
        # catalog identity. Production supplies this proof through model_faces.
        proof = {'path': str(path), 'sha256': hashlib.sha256(face_raw).hexdigest(), 'sourceIndex': 1}
        self.metadata = model_edits.register_session(self.token, [str(self.source)], rig, companions=[proof])
        return path, body_raw, face_raw

    def test_full_face_bundle_and_installer_reference_for_multiple_members(self):
        for member in (1, 6, 201):
            with self.subTest(member=member):
                face, body_raw, face_raw = self.face_session(member)
                record = next(row for row in self.metadata['outlines']['meshes'] if row['sourceIndex'] == 1)
                state = dict(self.empty, outlines=[{'id': record['id'], 'factor': 1,
                    'vertices': [{'vertex': 0, 'value': .25}]}])
                result = flow.create_package(self.token, state, output_root=self.output,
                    repo_root=self.runtime, cache_root=self.cache, display_name='Mouth outline',
                    character_id=None, include_face_edits=True, job=Job(secrets.token_hex(6), 'viewer_mod_package'))
                with zipfile.ZipFile(result['mod_package']['package_path']) as archive:
                    fields = {node.targets[0].id: ast.literal_eval(node.value)
                              for node in ast.parse(archive.read('modinstall.txt').decode()).body}
                    self.assertEqual(fields['chara_id'], member)
                    self.assertTrue(fields['costume_facedynamic_file'])
                    body_proof = next(row for row in result['face_identity'] if row['role'] == 'costume_file')
                    bundle_identity.verify_identity_only(body_raw, archive.read(fields['costume_file']), body_proof['namespace'])
                    saved_face = archive.read(fields['costume_facedynamic_file'])
                    saved_preview = Path(result['preview_paths'][1]).read_bytes()
                    face_proof = next(row for row in result['face_identity'] if row['role'] == 'costume_facedynamic_file')
                    bundle_identity.verify_identity_only(saved_preview, saved_face, face_proof['namespace'])
                    self.assertNotEqual(saved_face, face_raw)
                    old = model_edits._inspect(face_raw); new = model_edits._inspect(saved_preview)
                    mesh_key = next(key for key, obj in old['objects'].items() if obj.type.name == 'Mesh')
                    self.assertEqual({key for key in old['objects'] if old['objects'][key].type.name != 'AssetBundle' and old['objects'][key].get_raw_data() != new['objects'][key].get_raw_data()}, {mesh_key})
                    self.assertEqual(sum(obj.type.name == 'Mesh' for obj in UnityPy.load(saved_face).objects), 1)
                self.assertEqual(self.source.read_bytes(), body_raw); self.assertEqual(face.read_bytes(), face_raw)
                self.assertTrue(result['metadata']['hasFaceCompanions'])

    def test_including_already_baked_face_and_explicit_exclusion(self):
        face, body_raw, face_raw = self.face_session(6)
        for include in (False, True):
            result = self.package(self.empty, include_face_edits=include)
            with zipfile.ZipFile(result['mod_package']['package_path']) as archive:
                fields = {node.targets[0].id: ast.literal_eval(node.value)
                          for node in ast.parse(archive.read('modinstall.txt').decode()).body}
                self.assertEqual(bool(fields['costume_facedynamic_file']), include)
                if include:
                    face_proof = next(row for row in result['face_identity'] if row['role'] == 'costume_facedynamic_file')
                    bundle_identity.verify_identity_only(face_raw, archive.read(fields['costume_facedynamic_file']), face_proof['namespace'])
        self.assertEqual(self.source.read_bytes(), body_raw); self.assertEqual(face.read_bytes(), face_raw)

    def test_face_inclusion_changes_thumbnail_binding_and_forged_companion_is_rejected(self):
        face, _, _ = self.face_session(6)
        no_face, _, _ = thumbs._viewer_binding(self.token, self.empty, 6, None, None)
        include, _, _ = thumbs._viewer_binding(self.token, self.empty, 6, None, None, include_face_edits=True)
        exclude, _, _ = thumbs._viewer_binding(self.token, self.empty, 6, None, None, include_face_edits=False)
        self.assertNotEqual(no_face, include)
        self.assertNotEqual(no_face, exclude); self.assertNotEqual(include, exclude)
        self.assertNotIn('include_face_edits', no_face); self.assertIs(exclude['include_face_edits'], False)
        exported = self.export(self.empty, allow_empty=True)
        context = model_edits.mod_source_context(self.token)
        selected, faces = flow._package_inputs(context, exported)
        from webtools.core import viewer_mod_package
        for changes in ({'source_sha256': '0' * 64}, {'owner': 201}, {'platform': 'ios'}):
            forged = copy.deepcopy(faces); forged[0].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                viewer_mod_package.package_saved_export(selected, self.output / ('forged-' + secrets.token_hex(4)),
                    display_name='Rejected', chara_id=6, face_companions=forged)

    def test_existing_face_reference_is_preserved_when_omitted_and_disabled_only_explicitly(self):
        self.face_session(6)
        first = self.package(self.empty, include_face_edits=True)
        package = Path(first['mod_package']['package_path'])
        original = package.read_bytes()
        from webtools.core import viewer_mod_package
        with zipfile.ZipFile(package) as archive:
            old_fields = {node.targets[0].id: ast.literal_eval(node.value)
                          for node in ast.parse(archive.read('modinstall.txt').decode()).body}
            face_bytes = archive.read(old_fields['costume_facedynamic_file'])
        for flag in (None, False):
            with self.subTest(include=flag):
                result = viewer_mod_package.package_saved_export({'preview_paths': [str(package)], 'originals_preserved': True},
                    self.output / ('repack-' + str(flag)), display_name='Repacked', include_face_edits=flag)
                with zipfile.ZipFile(result['package_path']) as archive:
                    fields = {node.targets[0].id: ast.literal_eval(node.value)
                              for node in ast.parse(archive.read('modinstall.txt').decode()).body}
                    self.assertEqual(bool(fields['costume_facedynamic_file']), flag is None)
                    if flag is None:
                        self.assertEqual(archive.read(fields['costume_facedynamic_file']), face_bytes)
                    else:
                        self.assertFalse(fields['costume_facedynamic_file_ios'])
                        self.assertTrue(any(archive.read(info) == face_bytes for info in archive.infolist() if not info.is_dir()))
        self.assertEqual(package.read_bytes(), original)

    def test_face_graph_rewrites_dependencies_and_refuses_dangling_explicit_exclusion(self):
        face, body_raw, face_raw = self.face_session(6, dependency=True)
        first = self.package(self.empty, include_face_edits=True)
        package = Path(first['mod_package']['package_path'])
        with zipfile.ZipFile(package) as archive:
            fields = {node.targets[0].id: ast.literal_eval(node.value)
                      for node in ast.parse(archive.read('modinstall.txt').decode()).body}
            body_exec, face_exec = archive.read(fields['costume_file']), archive.read(fields['costume_facedynamic_file'])
        proofs = {row['role']: row for row in first['face_identity']}
        face_proof, body_proof = proofs['costume_facedynamic_file'], proofs['costume_file']
        identities = bundle_identity._cab_mapping(bundle_identity._cab_names(face_raw), face_proof['namespace'])
        runtime = bundle_identity._runtime_names(face_raw, face_proof['namespace'])
        bundle_identity.verify_identity_only(body_raw, body_exec, body_proof['namespace'], _identities=identities, _bundle_names=runtime)
        bundle_identity.verify_identity_only(face_raw, face_exec, face_proof['namespace'])
        from webtools.core import viewer_mod_package
        with self.assertRaisesRegex(ValueError, 'Reimport the original body'):
            viewer_mod_package.package_saved_export({'preview_paths': [str(package)], 'originals_preserved': True},
                self.output / 'private-face-off', display_name='Must not break', include_face_edits=False)
        # A raw body retains its original public dependency unchanged when its
        # automatic face is excluded; only private ZIP dependencies need refusal.
        off = self.package(self.empty, include_face_edits=False)
        with zipfile.ZipFile(off['mod_package']['package_path']) as archive:
            fields = {node.targets[0].id: ast.literal_eval(node.value)
                      for node in ast.parse(archive.read('modinstall.txt').decode()).body}
            self.assertEqual(archive.read(fields['costume_file']), body_raw)
        self.assertEqual(self.source.read_bytes(), body_raw); self.assertEqual(face.read_bytes(), face_raw)

    def test_face_graph_is_isolated_per_platform_for_ios_and_dual_rina(self):
        from webtools.core import viewer_mod_package
        def native(platform, owner, label, dependency=False):
            environment = UnityPy.load(costume_fixture())
            for asset in environment.assets:
                asset._m_target_platform = platform; asset.mark_changed()
            for obj in environment.objects:
                if obj.type.name == 'Texture2D':
                    tree = obj.read_typetree(); tree['m_Name'] = f'ch{owner:04d}_co0001_body'; obj.save_typetree(tree)
                elif obj.type.name == 'AssetBundle':
                    tree = obj.read_typetree(); tree['m_Name'] = tree['m_AssetBundleName'] = label + '.unity3d'
                    tree['m_Dependencies'] = ['face.unity3d'] if dependency else []
                    obj.save_typetree(tree)
            return environment.file.save()
        for dual in (False, True):
            with self.subTest(dual=dual):
                owner = 209 if dual else 6
                payloads = {'ios.unity': native(9, owner, 'ios', True), 'iosface.unity': native(9, owner, 'face')}
                fields = {'chara_id': owner, 'costume_file': 'ios.unity', 'costume_facedynamic_file': 'iosface.unity'}
                if dual:
                    payloads.update({'android.unity': native(13, owner, 'android', True),
                        'androidR.unity': native(13, owner, 'androidR', True), 'androidface.unity': native(13, owner, 'face'),
                        'iosR.unity': native(9, owner, 'iosR', True)})
                    fields.update(costume_file='android.unity', rina_unmask_costume_file='androidR.unity',
                        costume_file_ios='ios.unity', rina_unmask_costume_file_ios='iosR.unity',
                        costume_facedynamic_file='androidface.unity', costume_facedynamic_file_ios='iosface.unity')
                source = self.root / ('dual.zip' if dual else 'ios.zip')
                with zipfile.ZipFile(source, 'w') as archive:
                    archive.writestr('modinstall.txt', '\n'.join(key + '=' + repr(value) for key, value in fields.items()))
                    for name, raw in payloads.items(): archive.writestr(name, raw)
                before = source.read_bytes()
                result = viewer_mod_package.package_saved_export({'preview_paths': [str(source)], 'originals_preserved': True},
                    self.output / ('dual' if dual else 'ios'), display_name='Private Face', include_face_edits=True)
                self.assertEqual(len(result['face_identity']), 6 if dual else 2)
                with zipfile.ZipFile(result['package_path']) as archive:
                    manifest = {node.targets[0].id: ast.literal_eval(node.value)
                                for node in ast.parse(archive.read('modinstall.txt').decode()).body}
                    for platform in ('android', 'ios') if dual else ('ios',):
                        rows = [row for row in result['face_identity'] if row['platform'] == platform]
                        identities, runtime = {}, {}
                        for row in rows:
                            raw = payloads[fields[row['role']]]
                            identities.update(bundle_identity._cab_mapping(bundle_identity._cab_names(raw), row['namespace']))
                            runtime.update(bundle_identity._runtime_names(raw, row['namespace']))
                        # Neutral files deliberately reuse their original CAB;
                        # own IDs still differ, while the unique Face runtime
                        # dependency maps to the correct native platform.
                        for row in rows:
                            bundle_identity.verify_identity_only(payloads[fields[row['role']]], archive.read(manifest[row['role']]),
                                row['namespace'], _identities=identities, _bundle_names=runtime)
                self.assertEqual(source.read_bytes(), before)

    def test_mia_lanzhu_runtime_owner_is_encoded_as_legacy_native_manifest_for_face_and_body(self):
        from webtools.core import member_identity, viewer_mod_package
        for runtime in (211, 212):
            native = member_identity.native_from_member(runtime)
            with self.subTest(runtime=runtime):
                face, body_raw, face_raw = self.face_session(native)
                context = model_edits.mod_source_context(self.token)
                hints = flow.metadata(context, repo_root=self.runtime, cache_root=self.cache)
                self.assertEqual(hints['characterId'], runtime)
                for include in (False, True):
                    thumbnail_token = ''
                    if include:
                        params = {'kind': 'viewer', 'token': self.token, 'state': self.empty, 'character_id': runtime,
                            'counterpart_path': None, 'selected_variant': None, 'include_face_edits': True}
                        plan = thumbs.plan(params); self.assertEqual(plan['items'][0]['characterId'], runtime)
                        stream = io.BytesIO(); Image.new('RGBA', (256, 256), (40, 80, 160, 255)).save(stream, format='PNG')
                        thumbs.store({'token': plan['token'], 'item_id': plan['items'][0]['id'], 'cache_key': plan['items'][0]['cacheKey'],
                            'profile_digest': plan['profileDigest'], 'png': 'data:image/png;base64,' + base64.b64encode(stream.getvalue()).decode(),
                            'render': {'quality': {'enabled': True, 'ready': True}, 'subjectPixels': 128, 'triangles': 20}})
                        thumbnail_token = plan['token']
                    result = flow.create_package(self.token, self.empty, output_root=self.output,
                        repo_root=self.runtime, cache_root=self.cache, display_name='Native owner boundary',
                        character_id=runtime, include_face_edits=include, thumbnail_token=thumbnail_token,
                        job=Job(secrets.token_hex(6), 'viewer_mod_package'))
                    if include:
                        self.assertEqual(result['mod_package']['thumbnail']['characterId'], runtime)
                    self.assertEqual(result['mod_package']['character_id'], runtime)
                    package = Path(result['mod_package']['package_path'])
                    with zipfile.ZipFile(package) as archive:
                        fields = {node.targets[0].id: ast.literal_eval(node.value)
                                  for node in ast.parse(archive.read('modinstall.txt').decode()).body}
                        self.assertEqual(fields['chara_id'], native)
                        self.assertEqual(member_identity.member_from_native(fields['chara_id']), runtime)
                        self.assertEqual(bool(fields['costume_facedynamic_file']), include)
                    metadata = flow._manifest_metadata({'containers': [{'raw': package.read_bytes()}]}, 'en')
                    self.assertEqual(metadata['owner'], runtime)
                    # Existing literal manifests keep their legacy native IDs;
                    # the response still identifies the runtime UI recipient.
                    repacked = viewer_mod_package.package_saved_export({'preview_paths': [str(package)], 'originals_preserved': True},
                        self.output / ('repack-' + str(runtime) + str(include)), display_name='Existing owner', chara_id=runtime)
                    self.assertEqual(repacked['chara_id'], runtime)
                    with zipfile.ZipFile(repacked['package_path']) as archive:
                        again = {node.targets[0].id: ast.literal_eval(node.value)
                                 for node in ast.parse(archive.read('modinstall.txt').decode()).body}
                        self.assertEqual(again['chara_id'], native)
                auto = viewer_mod_package.package_saved_export({'preview_paths': [str(self.source)], 'originals_preserved': True},
                    self.output / ('auto-' + str(runtime)), display_name='Native automatic owner')
                self.assertEqual(auto['chara_id'], runtime)
                self.assertEqual(self.source.read_bytes(), body_raw); self.assertEqual(face.read_bytes(), face_raw)

    def test_pair_limit_and_failed_package_cleanup_do_not_publish_partial_mesh_outputs(self):
        operations = self.mesh_state(deleteFaces=[0])
        with self.assertRaisesRegex(ValueError, 'paired'):
            self.package(self.empty, mesh_state=operations, counterpart_path=str(self.source), selected_variant='primary')
        self.assertFalse(self.output.exists())
        with patch('webtools.core.viewer_mod_package.package_saved_export', side_effect=ValueError('forced package failure')):
            with self.assertRaisesRegex(ValueError, 'forced package failure'):
                self.package(self.empty, mesh_state=operations)
        self.assertEqual(list(self.output.iterdir()), [])
        self.assertEqual(self.source.read_bytes(), self.raw)

    def test_verified_non_rina_derived_body_with_rina_texture_and_automatic_face_needs_no_rina_pair(self):
        face, body_raw, face_raw = self.face_session(6, body_member=209)
        # This is an explicit mocked verification boundary, not a fabricated
        # original-game import receipt for neutral fixture bytes. The real
        # owner_for_context verifies signed source hashes and typed provenance.
        hint = {'character_id': 6, 'suit_id': 60001, 'region': 'gl', 'derived': True, 'operations': ['costume']}
        from webtools.core import viewer_mod_sources
        self.assertEqual(viewer_mod_sources._model_facts(body_raw)['owner'], 209)
        with patch.object(viewer_physics_runtime, 'owner_for_context', return_value=hint):
            result = self.package(self.empty, include_face_edits=True)
        with zipfile.ZipFile(result['mod_package']['package_path']) as archive:
            fields = {node.targets[0].id: ast.literal_eval(node.value)
                      for node in ast.parse(archive.read('modinstall.txt').decode()).body}
            self.assertEqual(fields['chara_id'], 6)
            self.assertFalse(fields['rina_unmask_costume_file'])
            self.assertTrue(fields['costume_facedynamic_file'])
            self.assertEqual(len(result['face_identity']), 2)
            body_proof = next(row for row in result['face_identity'] if row['role'] == 'costume_file')
            bundle_identity.verify_identity_only(body_raw, archive.read(fields['costume_file']), body_proof['namespace'])
        self.assertEqual(result['metadata']['characterId'], 6)
        self.assertEqual(result['metadata']['derivedOwner'], hint)
        self.assertEqual(self.source.read_bytes(), body_raw); self.assertEqual(face.read_bytes(), face_raw)

    def test_derived_owner_is_a_hint_and_does_not_create_original_game_receipts(self):
        context = model_edits.mod_source_context(self.token)
        hint = {'character_id': 201, 'suit_id': 1, 'region': 'gl', 'derived': True, 'operations': ['part', 'edit']}
        with patch.object(viewer_physics_runtime, 'owner_for_context', return_value=hint), \
             patch('webtools.core.viewer_mod_sources.game_context', return_value=[]):
            metadata = flow.metadata(context, repo_root=self.runtime, cache_root=self.cache)
        self.assertEqual(metadata['characterId'], 201)
        self.assertEqual(metadata['derivedOwner'], hint)
        self.assertFalse(metadata['requiresCounterpart'])
        self.assertEqual(flow.cached_receipts(context, self.cache), [])


if __name__ == '__main__':
    unittest.main()
