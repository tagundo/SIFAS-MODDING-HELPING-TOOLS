"""Real HTTP boundaries and serialized mesh round trips for workbench features."""
import http.client
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
from webtools.jobs import MANAGER
from webtools.server import Handler
from webtools.core import game_motions, viewer_mesh_tools, viewer_transplants


class WorkbenchHTTPBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = 'http://127.0.0.1:' + str(cls.server.server_port)
        cls.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(3)

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.library = self.root / 'sukusta'
        self.library.mkdir()
        environment = patch.dict(os.environ, {'SUKUSTA_DIR': str(self.library)})
        environment.start(); self.addCleanup(environment.stop)
        self.token = 'a' * 32
        self.mesh = {'source': 0, 'file': 0, 'id': '100'}
        self.body = {'version': 1, 'savedSettingsEnabled': True, 'edits': []}
        self.mesh_state = {'version': 1, 'meshes': [{'mesh': self.mesh, 'deleteFaces': [0]}]}
        self.motion = {'region': 'gl', 'character': '101', 'category': 'home', 'motion': '1', 'download': False}
        self.transplant = {'token': self.token, 'state': self.body, 'donor': str(self.library / 'donor.unity'),
                           'variant': 'primary', 'operation': 'costume', 'partRoot': '',
                           'cutLow': .5, 'cutHigh': .96, 'region': 'lower'}

    def request(self, route, payload=None, *, raw=None, headers=None):
        data = json.dumps(payload).encode() if payload is not None else raw
        request = urllib.request.Request(self.url + route, data=data,
                                        headers={'Content-Type': 'application/json', **(headers or {})})
        try:
            response = self.opener.open(request, timeout=30)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, json.loads(response.read())

    def headers_only(self, route, headers):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        self.addCleanup(connection.close)
        connection.putrequest('POST', route)
        for name, value in headers:
            connection.putheader(name, value)
        connection.endheaders()
        response = connection.getresponse()
        return response.status, json.loads(response.read())

    def finish(self, job_id):
        job = MANAGER.get(job_id)
        deadline = time.monotonic() + 5
        while not job.is_done and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue(job.is_done)
        self.assertEqual(job.status, 'done')
        return job

    def backend_patch(self, module, name, **kwargs):
        context = patch.object(module, name, autospec=True, **kwargs)
        mocked = context.start(); self.addCleanup(context.stop)
        return mocked


class ViewerWorkbenchRouteTests(WorkbenchHTTPBase):
    def test_mesh_routes_forward_identity_and_fixed_output_folder(self):
        inspect = self.backend_patch(viewer_mesh_tools, 'inspect', return_value={'meshes': []})
        data = self.backend_patch(viewer_mesh_tools, 'data', return_value={'positions': []})
        export = self.backend_patch(viewer_mesh_tools, 'export', return_value={'preview_paths': []})
        for operation, payload in (
            ('inspect', {'token': self.token}),
            ('data', {'token': self.token, 'mesh': self.mesh}),
            ('export', {'token': self.token, 'state': self.mesh_state, 'bodyState': self.body}),
        ):
            self.assertEqual(self.request('/api/viewer/mesh/' + operation, payload, headers={'Origin': self.url})[0], 200)
        inspect.assert_called_once_with(self.token)
        data.assert_called_once_with(self.token, self.mesh)
        export.assert_called_once_with(self.token, self.mesh_state, self.library / 'modded/viewer', body_state=self.body)

    def test_motion_catalog_bounds_queries_and_preserves_keyword_signature(self):
        catalog = self.backend_patch(game_motions, 'catalog', return_value={'motions': []})
        status, response = self.request('/api/viewer/game/motions/catalog?region=gl&character=101&category=voice&search=hello&lang=ko')
        self.assertEqual(status, 200, response)
        catalog.assert_called_once_with(Path.cwd(), language='ko', region='gl', character='101', category='voice', search='hello', offset='0', song_type='all')
        catalog.reset_mock()
        for query in ('category=home&category=mv', 'output_dir=/tmp', 'search=' + 'x' * 2049):
            self.assertEqual(self.request('/api/viewer/game/motions/catalog?' + query)[0], 400)
        catalog.assert_not_called()

    def test_motion_import_validates_before_job_and_uses_app_context(self):
        record = {'resources': [], 'download': False}
        validate = self.backend_patch(game_motions, 'validate_selection', return_value=record)
        run = self.backend_patch(game_motions, 'run_import', return_value='Ready')
        status, response = self.request('/api/viewer/game/motions/import?lang=ja', self.motion)
        self.assertEqual(status, 200, response)
        job = self.finish(response['job_id'])
        validate.assert_called_once_with(Path.cwd(), self.motion, 'ja')
        run.assert_called_once_with(job, repo_root=Path.cwd(), output_root=self.library / 'extracted/game-motions', record=record)
        validate.side_effect = ValueError('Motion no longer exists')
        with patch.object(MANAGER, 'create') as create:
            self.assertEqual(self.request('/api/viewer/game/motions/import', self.motion)[0], 400)
        create.assert_not_called()

    def test_transplant_routes_use_strict_signatures_and_validate_before_job(self):
        inspect = self.backend_patch(viewer_transplants, 'inspect_donor', return_value={'parts': []})
        validate = self.backend_patch(viewer_transplants, 'validate_request', return_value={'validated': True})
        run = self.backend_patch(viewer_transplants, 'run_transplant', return_value='Ready')
        status, response = self.request('/api/viewer/transplant/inspect', {'donor': self.transplant['donor'], 'variant': 'unmasked'})
        self.assertEqual(status, 200, response)
        inspect.assert_called_once_with(self.transplant['donor'], 'unmasked', cache_root=self.library / '.viewer-cache')
        status, response = self.request('/api/viewer/transplant/run', self.transplant)
        self.assertEqual(status, 200, response)
        job = self.finish(response['job_id'])
        validate.assert_called_once_with(self.transplant)
        run.assert_called_once_with(job, {'validated': True}, output_root=self.library / 'modded/viewer', cache_root=self.library / '.viewer-cache')
        validate.side_effect = ValueError('Cut planes are reversed')
        with patch.object(MANAGER, 'create') as create:
            self.assertEqual(self.request('/api/viewer/transplant/run', self.transplant)[0], 400)
        create.assert_not_called()

    def test_large_source_bound_part_mask_reaches_validation_with_a_fixed_upper_bound(self):
        validate = self.backend_patch(viewer_transplants, 'validate_request', return_value={'validated': True})
        run = self.backend_patch(viewer_transplants, 'run_transplant', return_value='Ready')
        payload = {**self.transplant, 'operation': 'part', 'partRoot': '', 'partSelectionMode': 'triangles',
                   'partRoots': [], 'includeDescendants': True, 'triangleIndices': list(range(100000)),
                   'donorSha256': 'a' * 64, 'donorSelectionFingerprint': 'b' * 64, 'donorRenderer': '12', 'donorMesh': '1'}
        self.assertGreater(len(json.dumps(payload).encode()), 512 * 1024)
        status, response = self.request('/api/viewer/transplant/run', payload)
        self.assertEqual(status, 200, response)
        self.finish(response['job_id'])
        validate.assert_called_once_with(payload)
        self.assertEqual(run.call_count, 1)
        validate.reset_mock()
        self.assertEqual(self.headers_only('/api/viewer/transplant/run', [('Content-Length', str(4 * 1024 * 1024 + 1))])[0], 400)
        validate.assert_not_called()

    def test_all_feature_posts_reject_extra_paths_and_cross_origin_calls(self):
        routes = [
            ('/api/viewer/game/motions/import', self.motion),
            ('/api/viewer/mesh/inspect', {'token': self.token}),
            ('/api/viewer/mesh/data', {'token': self.token, 'mesh': self.mesh}),
            ('/api/viewer/mesh/export', {'token': self.token, 'state': self.mesh_state, 'bodyState': self.body}),
            ('/api/viewer/transplant/inspect', {'donor': self.transplant['donor'], 'variant': 'primary'}),
            ('/api/viewer/transplant/run', self.transplant),
        ]
        with patch.object(MANAGER, 'create') as create:
            for route, payload in routes:
                with self.subTest(route=route):
                    self.assertEqual(self.request(route, {**payload, 'output_dir': '/tmp/escape'})[0], 400)
                    self.assertEqual(self.request(route, raw=b'invalid json')[0], 400)
                    for origin in ('null', 'https://untrusted.invalid', self.url + '/other', self.url + '?q=1', self.url.replace('http:', 'file:')):
                        self.assertEqual(self.request(route, payload, headers={'Origin': origin})[0], 403)
                    self.assertEqual(self.request(route, payload, headers={'Sec-Fetch-Site': 'cross-site'})[0], 403)
        create.assert_not_called()

    def test_repeated_origin_and_unbounded_bodies_rejected_before_reading(self):
        for route in ('/api/viewer/game/motions/import', '/api/viewer/mesh/export', '/api/viewer/transplant/run'):
            for headers in (
                [('Content-Length', '0')], [('Content-Length', '-1')], [('Content-Length', 'invalid')],
                [('Content-Length', str(viewer_mesh_tools.MAX_REQUEST_BYTES + 1))],
                [('Content-Length', '12'), ('Transfer-Encoding', 'chunked')],
                [('Content-Length', '12'), ('Origin', self.url), ('Origin', self.url)],
            ):
                with self.subTest(route=route, headers=headers):
                    expected = 403 if sum(name == 'Origin' for name, _ in headers) > 1 else 400
                    self.assertEqual(self.headers_only(route, headers)[0], expected)

    def test_invalid_tokens_do_not_reach_backends(self):
        inspect = self.backend_patch(viewer_mesh_tools, 'inspect', return_value={})
        validate = self.backend_patch(viewer_transplants, 'validate_request', return_value={})
        for token in ('../escape', 'A' * 32, 'a' * 31, 123, None, ['a' * 32]):
            self.assertEqual(self.request('/api/viewer/mesh/inspect', {'token': token})[0], 400)
            self.assertEqual(self.request('/api/viewer/transplant/run', {**self.transplant, 'token': token})[0], 400)
        inspect.assert_not_called(); validate.assert_not_called()

    def test_expired_sessions_permissions_and_timeouts_have_correct_status(self):
        inspect = self.backend_patch(viewer_mesh_tools, 'inspect', side_effect=ValueError('Editing session expired'))
        status, response = self.request('/api/viewer/mesh/inspect', {'token': self.token})
        self.assertEqual(status, 400); self.assertIn('expired', response['error'])
        inspect.side_effect = PermissionError('Outside allowed folders')
        self.assertEqual(self.request('/api/viewer/mesh/inspect', {'token': self.token})[0], 403)
        inspect.side_effect = TimeoutError('Editing is busy')
        self.assertEqual(self.request('/api/viewer/mesh/inspect', {'token': self.token})[0], 503)

    def test_output_symlinks_cannot_redirect_motion_imports(self):
        outside = self.root / 'outside'
        outside.mkdir()
        (self.library / 'extracted').mkdir()
        (self.library / 'extracted/game-motions').symlink_to(outside, target_is_directory=True)
        self.backend_patch(game_motions, 'validate_selection', return_value={})
        with patch.object(MANAGER, 'create') as create:
            self.assertEqual(self.request('/api/viewer/game/motions/import', self.motion)[0], 403)
        create.assert_not_called()


class ViewerWorkbenchRealMeshHTTPTests(WorkbenchHTTPBase):
    def setUp(self):
        super().setUp()
        try:
            import UnityPy  # noqa: F401
            import numpy  # noqa: F401
        except ImportError:
            self.skipTest('UnityPy and numpy are required for serialized mesh checks')
        source = self.library / 'extracted/original.unity'
        source.parent.mkdir()
        source.write_bytes((Path(__file__).parent / 'fixtures/viewer_persistence.unity').read_bytes())
        self.source, self.original = source, source.read_bytes()
        status, prepared = self.request('/api/viewer/prepare', {'paths': [str(source)], 'rigged': True, 'auto_face': False})
        self.assertEqual(status, 200, prepared)
        self.assertTrue(prepared['editing']['available'], prepared['editing'])
        self.token = prepared['editing']['token']

    def test_triangle_delete_writes_only_new_serialized_copy(self):
        status, inspected = self.request('/api/viewer/mesh/inspect', {'token': self.token})
        self.assertEqual(status, 200, inspected)
        mesh = next(item['mesh'] for item in inspected['meshes'] if item['available'])
        status, data = self.request('/api/viewer/mesh/data', {'token': self.token, 'mesh': mesh})
        self.assertEqual(status, 200, data)
        self.assertTrue(data['triangles'])
        status, result = self.request('/api/viewer/mesh/export', {'token': self.token,
            'state': {'version': 1, 'meshes': [{'mesh': mesh, 'deleteFaces': [0]}]}, 'bodyState': None})
        self.assertEqual(status, 200, result)
        output = Path(result['preview_paths'][0])
        self.assertTrue(output.is_relative_to(self.library / 'modded/viewer'))
        self.assertNotEqual(output, self.source)
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(Path(result['original_paths'][0]).read_bytes(), self.original)
        self.assertEqual(result['summary'][0]['deletedFaces'], 1)
        _, records = viewer_mesh_tools._mesh_records(output.read_bytes(), 0)
        record = next(record for record in records if record[0] == mesh)
        remaining, _, _ = viewer_mesh_tools._triangles(record[2], record[2]['m_VertexData']['m_VertexCount'])
        self.assertEqual(len(remaining), len(data['triangles']) - 1)
        self.assertEqual(record[2]['m_VertexData']['m_VertexCount'], len(data['positions']))
        self.assertTrue(any(path.endswith('mesh-recipe.json') for path in result['output_paths']))

    def test_forged_identity_and_invalid_body_state_cannot_write(self):
        status, inspected = self.request('/api/viewer/mesh/inspect', {'token': self.token})
        self.assertEqual(status, 200, inspected)
        mesh = next(item['mesh'] for item in inspected['meshes'] if item['available'])
        status, result = self.request('/api/viewer/mesh/data', {'token': self.token, 'mesh': {**mesh, 'source': 999}})
        self.assertEqual(status, 400, result)
        for body in ('invalid', [], True):
            with self.subTest(body=body):
                status, response = self.request('/api/viewer/mesh/export', {'token': self.token,
                    'state': {'version': 1, 'meshes': [{'mesh': mesh, 'deleteFaces': [0]}]}, 'bodyState': body})
                self.assertEqual(status, 400, response)
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertFalse(list((self.library / 'modded/viewer').glob('mesh-edit-*')))


if __name__ == '__main__':
    unittest.main()
