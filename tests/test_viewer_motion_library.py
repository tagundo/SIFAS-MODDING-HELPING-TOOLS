"""Retained AnimationClip inputs stay separate from model editing identities."""
import copy
import hashlib
from http.server import ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

from webtools.core import game_motions, model_edits, model_viewer
from webtools.server import Handler


def make_motion_library_fixture(directory):
    """Two native neutral models with different IDs and two clip-only banks."""
    import UnityPy
    from generate_viewer_physics_fixture import fixture_bytes
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=True)
    base = fixture_bytes(native=True)
    # The native-physics fixture intentionally has no expression bank. Add the
    # genuine neutral fixture's one morph so inspection restoration is tested.
    source = UnityPy.load((Path(__file__).parent / 'fixtures/viewer_rig.unity').read_bytes())
    shapes = next(obj.read_typetree()['m_Shapes'] for obj in source.objects if obj.type.name == 'Mesh')
    env = UnityPy.load(base)
    for obj in env.objects:
        if obj.type.name == 'Mesh':
            tree = obj.read_typetree(); tree['m_Shapes'] = copy.deepcopy(shapes); obj.save_typetree(tree)
        elif obj.type.name == 'SkinnedMeshRenderer':
            tree = obj.read_typetree(); tree['m_BlendShapeWeights'] = [0.]; obj.save_typetree(tree)
    base = env.file.save(packer='original')
    result = {}
    for label in ('a', 'b'):
        env = UnityPy.load(base)
        if label == 'a':
            for obj in env.objects:
                if obj.type.name == 'AnimationClip':
                    tree = obj.read_typetree(); tree['m_Name'] = 'Body A idle'; obj.save_typetree(tree)
        if label == 'b':
            asset = next(obj.assets_file for obj in env.objects if obj.type.name == 'Mesh')
            mapping = {identity: identity + 1000 for identity in asset.objects}
            mapping[3], mapping[11] = 1011, 1003

            def remap(value):
                if isinstance(value, dict):
                    if set(value) == {'m_FileID', 'm_PathID'} and value['m_FileID'] == 0:
                        value['m_PathID'] = mapping.get(value['m_PathID'], value['m_PathID'])
                    else:
                        for child in value.values(): remap(child)
                elif isinstance(value, (list, tuple)):
                    for child in value: remap(child)

            rewritten = {}
            for identity, obj in list(asset.objects.items()):
                tree = obj.read_typetree(); remap(tree)
                if obj.type.name == 'AnimationClip': tree['m_Name'] = 'Body B idle'
                obj.path_id = mapping[identity]; obj.save_typetree(tree); rewritten[obj.path_id] = obj
            asset.objects = dict(sorted(rewritten.items()))
        destination = directory / ('body-' + label + '.unity'); destination.write_bytes(env.file.save(packer='original')); result['body_' + label] = str(destination.resolve())
    for label, angle in (('a', 35), ('b', -50)):
        env = UnityPy.load(base)
        for obj in list(env.objects):
            if obj.type.name != 'AnimationClip':
                del obj.assets_file.objects[obj.path_id]
            else:
                tree = obj.read_typetree(); tree['m_Name'] = 'Library ' + label.upper()
                middle = tree['m_RotationCurves'][0]['curve']['m_Curve'][1]['value']
                middle.update(z=math.sin(math.radians(angle / 2)), w=math.cos(math.radians(angle / 2)))
                obj.save_typetree(tree)
        destination = directory / ('motion-' + label + '.unity'); destination.write_bytes(env.file.save(packer='original')); result['motion_' + label] = str(destination.resolve())
    return result


def make_many_motion_library_fixture(directory, counts=(10, 100, 400)):
    """Original-format clip banks with distinct visible poses, never game data."""
    import UnityPy
    directory = Path(directory)
    result = make_motion_library_fixture(directory)
    original = Path(result['motion_a']).read_bytes()
    for count in counts:
        env = UnityPy.load(original)
        source = next(obj for obj in env.objects if obj.type.name == 'AnimationClip')
        asset, tree = source.assets_file, source.read_typetree()
        asset.objects.clear()
        for index in range(count):
            obj = copy.copy(source); obj.path_id = 10000 + index
            value = copy.deepcopy(tree); value['m_Name'] = 'Stress motion %04d' % index
            angle = (index + .5) / count * .6 - .3
            value['m_RotationCurves'][0]['curve']['m_Curve'][1]['value'].update(z=angle, w=math.sqrt(1 - angle * angle))
            asset.objects[obj.path_id] = obj; obj.save_typetree(value)
        path = directory / ('stress-%d.unity' % count)
        path.write_bytes(env.file.save(packer='original'))
        result['bank_' + str(count)] = str(path.resolve())
    return result


def make_many_motion_source_fixture(directory, count=257):
    """One original-format pose per source, including long native-style paths."""
    import UnityPy
    directory = Path(directory)
    result = make_motion_library_fixture(directory)
    original = Path(result['motion_a']).read_bytes()
    source_directory = directory / ('Motion Imports ' + 'long-native-library-' * 5) / 'キャラクター 모션'
    source_directory.mkdir(parents=True, exist_ok=True)
    result['sources'] = []
    for index in range(count):
        env = UnityPy.load(original)
        obj = next(obj for obj in env.objects if obj.type.name == 'AnimationClip')
        tree = obj.read_typetree(); tree['m_Name'] = 'Source pose %04d' % index
        angle = (index + .5) / count * .6 - .3
        tree['m_RotationCurves'][0]['curve']['m_Curve'][1]['value'].update(z=angle, w=math.sqrt(1 - angle * angle))
        obj.save_typetree(tree)
        path = source_directory / ('pose-%04d.unity' % index)
        path.write_bytes(env.file.save(packer='original'))
        result['sources'].append(str(path.resolve()))
    return result


class MotionLibraryFixtureBase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name); self.library = self.root / 'library'; self.library.mkdir()
        self.paths = make_motion_library_fixture(self.library / 'extracted/3d_model')
        self.context = {'enabled': False, 'allow_download': False, 'repo_root': str(self.root), 'cache_dir': str(self.library / '.viewer-cache')}
        self.before = {path: Path(path).read_bytes() for path in self.paths.values()}

    def prepare(self, body='a', motions=('a', 'b')):
        return model_viewer.prepare([self.paths['body_' + body]], rigged=True,
            motion_paths=[self.paths['motion_' + label] for label in motions], face_context=self.context)


class RetainedMotionLibraryTests(MotionLibraryFixtureBase):
    def test_two_clip_banks_bind_to_each_new_body_without_changing_its_identity(self):
        rigs = []
        for body in ('a', 'b'):
            with self.subTest(body=body):
                prepared = self.prepare(body); rig = prepared['rig']; rigs.append(rig)
                self.assertTrue(rig['available']); self.assertEqual(prepared['stats']['meshes'], 1)
                self.assertEqual(prepared['stats']['textures'], 1, 'all original material texture pointers survive fixture source-ID remapping')
                names = [clip['name'] for clip in rig['clips']]
                self.assertIn('Library A', names); self.assertIn('Library B', names)
                self.assertIn('Body ' + body.upper() + ' idle', names)
                other = 'Body ' + ('B' if body == 'a' else 'A') + ' idle'; self.assertNotIn(other, names)
                for clip in rig['clips']:
                    if clip['name'].startswith('Library '):
                        self.assertGreater(clip['channels'], 0); self.assertTrue(clip.get('bindingComplete', True))
                token = prepared['id']
                model_edits.register_session(token, [self.paths['body_' + body]], rig,
                    companions=model_viewer.get_editing_companions(token))
                self.addCleanup(lambda token=token: model_edits._SESSIONS.pop(token, None))
                source = model_edits.mod_source_context(token)
                self.assertEqual([row['name'] for row in source['sources']], ['body-' + body + '.unity'])
                self.assertEqual(len(source['containers']), 1)
                self.assertEqual(source['containers'][0]['sha256'], hashlib.sha256(self.before[self.paths['body_' + body]]).hexdigest())
                target = next(node for node in source['nodes'] if node['name'] == 'BreastSize')
                exported = model_edits.export(token, {'version': 1, 'savedSettingsEnabled': True,
                    'edits': [{'node': target['node'], 'method': 'node', 'scale': [1.1, 1.1, 1.1]}]}, self.root / ('saved-' + body))
                self.assertEqual(len(exported['preview_paths']), 1); self.assertEqual(len(exported['original_paths']), 1)
                import UnityPy
                saved = UnityPy.load(Path(exported['preview_paths'][0]).read_bytes())
                saved_clips = [obj.read_typetree()['m_Name'] for obj in saved.objects if obj.type.name == 'AnimationClip']
                self.assertEqual(saved_clips, ['Body ' + body.upper() + ' idle'], 'saved body keeps its own clip but never embeds retained library banks')
        first = {bone['name']: bone['node'] for bone in rigs[0]['bones']}
        second = {bone['name']: bone['node'] for bone in rigs[1]['bones']}
        self.assertNotEqual(first['LeftUpLeg'], second['LeftUpLeg'], 'fixture changes runtime node order so binding cannot reuse stale node indices')
        for path, raw in self.before.items(): self.assertEqual(Path(path).read_bytes(), raw)

    def test_motion_limit_is_separate_from_eight_model_slots_and_invalid_inputs_fail_before_build(self):
        body, motion = self.paths['body_a'], self.paths['motion_a']
        prepared = model_viewer.prepare([body] * 8, rigged=True, motion_paths=[motion] * 32, face_context=self.context)
        self.assertTrue(prepared['rig']['available']); self.assertIn('Library A', [clip['name'] for clip in prepared['rig']['clips']])
        for count in (33, 256):
            prepared = model_viewer.prepare([body], rigged=True, motion_paths=[motion] * count, face_context=self.context)
            self.assertIn('Library A', [clip['name'] for clip in prepared['rig']['clips']])
        with patch.object(model_viewer, '_build') as build:
            for options in ({'motion_paths': [motion] * 257, 'rigged': True}, {'motion_paths': [motion], 'rigged': False}, {'motion_paths': 'bad', 'rigged': True}, {'motion_paths': [None], 'rigged': True}):
                with self.subTest(options=options), self.assertRaises(model_viewer.ModelViewerError):
                    model_viewer.prepare([body], face_context=self.context, **options)
            with self.assertRaises(model_viewer.ModelViewerError):
                model_viewer.prepare([body] * 9, rigged=True, motion_paths=[motion], face_context=self.context)
            with self.assertRaisesRegex(model_viewer.ModelViewerError, 'at most 256 source files. Selected: 257'):
                model_viewer.prepare([body], rigged=True, motion_paths=[motion] * 257, face_context=self.context)
            build.assert_not_called()

    def test_expanded_source_slots_keep_the_combined_192_mib_budget(self):
        # Each source and each separate selection fit; their combined size does
        # not. Increasing source slots must never split this shared byte budget.
        with patch.object(model_viewer.os.path, 'getsize', return_value=50 * 1024 * 1024), \
                patch.object(model_viewer, '_build') as build:
            with self.assertRaisesRegex(model_viewer.ModelViewerError, 'selected model files are too large'):
                model_viewer.prepare([self.paths['body_a']], rigged=True,
                    motion_paths=[self.paths['motion_a'], self.paths['motion_b'], self.paths['body_b']], face_context=self.context)
            build.assert_not_called()
        self.assertEqual(model_viewer.MAX_TOTAL_SOURCE_BYTES, 192 * 1024 * 1024)
        self.assertEqual(model_viewer.MAX_UNPACKED_BYTES, 192 * 1024 * 1024)
        self.assertEqual(model_viewer.MAX_GLB_BYTES, 64 * 1024 * 1024)

    def test_trusted_game_descriptor_is_retained_and_changed_bank_loses_trust(self):
        descriptor = {'version': 2, 'id': 'trusted-library-fixture', 'category': 'mv', 'label': 'Verified fixture action',
            'duration': 2, 'bodySegments': [], 'facialClips': [],
            'gaze': {'version': 1, 'segments': [{'start': 0, 'end': 2, 'target': [0, 1, 1]}]},
            'physics': {'profile': 'live', 'liveId': 12007, 'safeSwingBoneKnown': True, 'safeSwingBone': True}}
        motion = self.paths['motion_a']; game_motions._register([motion], descriptor)
        self.addCleanup(lambda: game_motions._IMPORTS.pop(motion, None))
        for body in ('a', 'b'):
            self.assertEqual(self.prepare(body)['rig']['motionTimelines'], [descriptor])
        import UnityPy
        env = UnityPy.load(Path(motion).read_bytes()); obj = next(obj for obj in env.objects if obj.type.name == 'AnimationClip')
        tree = obj.read_typetree(); tree['m_Name'] = 'Changed library'; obj.save_typetree(tree); Path(motion).write_bytes(env.file.save(packer='original'))
        self.assertEqual(self.prepare()['rig']['motionTimelines'], [], 'receipt trust is checked against current bank bytes, not just its filename')


class MotionLibraryHTTPGuardTests(MotionLibraryFixtureBase):
    def setUp(self):
        super().setUp()
        environment = patch.dict(os.environ, {'SUKUSTA_DIR': str(self.library)}); environment.start(); self.addCleanup(environment.stop)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.addCleanup(self.close)
        self.url = 'http://127.0.0.1:' + str(self.server.server_port)
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def close(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(3)

    def request(self, payload):
        request = urllib.request.Request(self.url + '/api/viewer/prepare', data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
        try: response = self.opener.open(request, timeout=60)
        except urllib.error.HTTPError as error: response = error
        with response: return response.status, json.loads(response.read())

    def test_http_motion_inputs_are_bounded_and_jailed_independently_of_models(self):
        base = {'paths': [self.paths['body_a']], 'motion_paths': [self.paths['motion_a']], 'rigged': True, 'auto_face': False}
        outside = self.root / 'outside.unity'; outside.write_bytes(self.before[self.paths['motion_b']])
        for field in ('paths', 'motion_paths'):
            payload = dict(base, **{field: [str(outside)]}); status, result = self.request(payload)
            self.assertEqual(status, 403, result)
        for extra in ({'motion_paths': [self.paths['motion_a']] * 257}, {'motion_paths': 'bad'}, {'motion_paths': [None]}, {'rigged': False}, {'paths': [self.paths['body_a']] * 9}, {'repo_root': str(self.root)}):
            status, result = self.request(dict(base, **extra)); self.assertEqual(status, 400, result)
        status, result = self.request(base); self.assertEqual(status, 200, result)
        token = result['editing']['token']; self.addCleanup(lambda: model_edits._SESSIONS.pop(token, None))
        self.assertEqual([row['name'] for row in model_edits.mod_source_context(token)['sources']], ['body-a.unity'])
        self.assertIn('Library A', [clip['name'] for clip in result['rig']['clips']])

    def test_http_257_source_limit_has_precise_details_before_loading_assets(self):
        with patch.object(model_viewer, 'prepare') as prepare:
            status, result = self.request({'paths': [self.paths['body_a']], 'motion_paths': [self.paths['motion_a']] * 257,
                                           'rigged': True, 'auto_face': False})
            self.assertEqual(status, 400, result)
            self.assertEqual(result['error_code'], 'motion_source_limit')
            self.assertEqual(result['max_motion_files'], 256)
            self.assertEqual(result['motion_files'], 257)
            self.assertIn('at most 256', result['error'])
            self.assertIn('Selected: 257', result['error'])
            prepare.assert_not_called()


if __name__ == '__main__':
    unittest.main()
