"""Selected game models: real encrypted sections, source preservation and jobs."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from webtools.core import game_models as game
from webtools.jobs import Job
from webtools.server import Handler
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen

try:
    import llas_asset_extractor as extractor
except ImportError:
    extractor = None


@unittest.skipUnless(extractor, "Elichika extractor is required")
class GameModelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.library = self.root / "library"
        self.output = self.library / "extracted/game-models"
        self.packs = self.root / "packs"
        self.packs.mkdir()
        self.payload = (Path(__file__).parent / "fixtures/viewer_rig.unity").read_bytes()
        self.encrypted = bytearray(self.payload)
        extractor.decrypt_section(self.encrypted, extractor.FIXED_KEY0, 7, 11)
        for region in ("gl", "jp"):
            directory = self.root / "assets/db" / region
            directory.mkdir(parents=True)
            with sqlite3.connect(directory / "masterdata.db") as db:
                db.executescript("CREATE TABLE m_suit(id INTEGER PRIMARY KEY,member_m_id INTEGER,name TEXT,model_asset_path TEXT,display_order INTEGER); CREATE TABLE m_suit_view(suit_master_id INTEGER,view_status INTEGER,model_asset_path TEXT); CREATE TABLE m_suit_attach(suit_master_id INTEGER,original_suit_master_id INTEGER,attach_key TEXT);")
                db.executemany("INSERT INTO m_suit VALUES(?,?,?,?,?)", [(1, 101, "k.first", "body", 5), (2, 209, "k.rina", "masked", 4), (3, 101, "k.colour", "body", 3)])
                db.execute("INSERT INTO m_suit_attach VALUES(3,1,'c1')")
                db.execute("INSERT INTO m_suit_view VALUES(2,2,'unmasked')")
            with sqlite3.connect(directory / ("dictionary_ja_k.db" if region == "jp" else "dictionary_ko_k.db")) as db:
                db.execute("CREATE TABLE m_dictionary(id TEXT,message TEXT)")
                db.executemany("INSERT INTO m_dictionary VALUES(?,?)", [("first", "첫 의상" if region == "gl" else "最初の衣装"), ("rina", "Rina outfit"), ("colour", "다른 색상")])
            with sqlite3.connect(directory / ("asset_a_ja.db" if region == "jp" else "asset_a_ko.db")) as db:
                db.executescript("CREATE TABLE member_model(asset_path TEXT,pack_name TEXT,head INTEGER,size INTEGER,key1 INTEGER,key2 INTEGER); CREATE TABLE member_model_dependency(asset_path TEXT,dependency TEXT,PRIMARY KEY(asset_path,dependency)); CREATE TABLE m_asset_package_mapping(package_key TEXT,pack_name TEXT,file_size INTEGER,metapack_name TEXT,metapack_offset INTEGER);")
                for model, pack in [("body", "basepack"), ("masked", "maskpack"), ("unmasked", "barepack"), ("colour", "colourpack")]:
                    db.execute("INSERT INTO member_model VALUES(?,?,0,?,7,11)", (model, pack, len(self.encrypted)))
                    for suit in (1, 2, 3):
                        db.execute("INSERT INTO m_asset_package_mapping VALUES(?,?,?,NULL,0)", (f"suit:{suit}", pack, len(self.encrypted)))
                db.execute("INSERT INTO member_model_dependency VALUES('body','colour')")
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, {"SUKUSTA_DIR": str(self.library)}).start()
        patch.object(extractor, "detect_game_candidates", return_value=[]).start()
        patch.object(extractor, "build_pack_roots", return_value=[str(self.packs)]).start()
        patch.object(extractor, "build_pack_index", side_effect=lambda root: {p.name: str(p) for p in Path(root).iterdir() if p.is_file()}).start()
        for name in ("basepack", "maskpack", "barepack", "colourpack"):
            (self.packs / name).write_bytes(self.encrypted)
        self.original = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.rglob("*") if p.is_file()}

    def select(self, suit="suit:1", **kwargs):
        return game.validate_selection(self.root, dict(region="gl", suit=suit, variant="primary", download=False, **kwargs), "ko")

    def run_import(self, record=None, job=None):
        job = job or Job("fake", "viewer_game_assets")
        game.run_import(job, repo_root=self.root, output_root=self.output, record=record or self.select())
        return job

    def test_catalog_region_language_search_and_exact_suit_identity(self):
        result = game.catalog(self.root, language="ko", character="101")
        self.assertEqual(result["region"], "gl")
        self.assertEqual({r["value"] for r in result["costumes"]}, {"suit:1", "suit:3"})
        self.assertIn("첫 의상", {r["label"] for r in result["costumes"]})
        result = game.catalog(self.root, language="ja", character="101")
        self.assertEqual(result["region"], "jp")
        self.assertIn("最初の衣装", {r["label"] for r in result["costumes"]})
        result = game.catalog(self.root, language="ko", search="Rina")
        self.assertEqual([r["value"] for r in result["costumes"]], ["suit:2"])
        self.assertEqual([v["value"] for v in result["costumes"][0]["variants"]], ["primary", "unmasked"])

    def test_ui_language_sets_default_region_independent_of_server_locale(self):
        (self.root / "config.json").write_text('{"locales":"ko"}')
        self.assertEqual(game.catalog(self.root, language="ja")["region"], "jp")
        (self.root / "config.json").write_text('{"locales":"ja"}')
        for language in ("en", "ko", "zh", "jp"):
            self.assertEqual(game.catalog(self.root, language=language)["region"], "gl")
        self.assertEqual(game.catalog(self.root, language="ja", region="gl")["region"], "gl")
        self.assertEqual(game.catalog(self.root, language="ko", region="jp")["region"], "jp")

    def test_local_decrypt_cache_and_all_original_files_unchanged(self):
        first = self.run_import().output_paths()
        self.assertEqual(len(first), 1)
        self.assertEqual(Path(first[0]).read_bytes(), self.payload)
        self.assertEqual(self.run_import().output_paths(), first)
        for name, digest in self.original.items():
            self.assertEqual(hashlib.sha256(Path(name).read_bytes()).hexdigest(), digest)

    def test_user_changed_extraction_is_preserved_and_never_reused(self):
        first = Path(self.run_import().output_paths()[0]); first.write_bytes(b'user edit')
        second = Path(self.run_import().output_paths()[0])
        self.assertNotEqual(first, second); self.assertEqual(first.read_bytes(), b'user edit')
        self.assertEqual(second.read_bytes(), self.payload)

    def test_exact_rina_unmasked_model_and_colour_attachment(self):
        unmasked = self.select("suit:2"); unmasked = game.validate_selection(self.root, {"region":"gl","suit":"suit:2","variant":"unmasked","download":False})
        self.assertEqual(unmasked["model"], "unmasked")
        colour = self.select("suit:3")
        self.assertEqual(colour["attach_key"], "c1"); self.assertEqual(colour["recolours"][0]["model"], "colour")
        calls = []
        def composite(base, source, out, **opts):
            calls.append(opts['attach_key']); Path(out).write_bytes(Path(base).read_bytes()); return 1
        with patch('adminui.tools.assets_extract._composite_recolour', side_effect=composite):
            result = self.run_import(colour).output_paths()
        self.assertEqual(calls, ['c1']); self.assertEqual(len(result), 1)
        self.assertEqual([p.name for p in Path(result[0]).parent.iterdir()], [Path(result[0]).name])

    def test_missing_colour_never_silently_opens_the_base_colour(self):
        with patch('adminui.tools.assets_extract._composite_recolour', return_value=0):
            with self.assertRaisesRegex(ValueError, 'base colour was not substituted'):
                self.run_import(self.select("suit:3"))
        self.assertFalse(list(self.output.glob('gl-*')))

    def test_cancelled_job_has_no_published_output_or_partial_folder(self):
        job = Job("cancel", "viewer_game_assets"); job.cancel_event.set()
        self.run_import(job=job)
        self.assertEqual(job.output_paths(), []); self.assertFalse(list(self.output.glob('gl-*')))

    def test_downloaded_section_is_identical_and_does_not_write_source_packs(self):
        (self.packs / 'basepack').unlink()
        record = self.select(); record['download'] = True
        with patch('webtools.core.model_faces._download_with_deadline', return_value=bytes(self.encrypted)) as download:
            self.assertEqual(Path(self.run_import(record).output_paths()[0]).read_bytes(), self.payload)
            self.assertEqual(self.run_import(record).output_paths(), self.run_import(record).output_paths())
            download.assert_called_once()
        self.assertFalse((self.packs / 'basepack').exists())

    def test_direct_404_uses_exact_metapack_range(self):
        record = self.select(); record['download'] = True
        record['metapack'] = {'name':'metapack','offset':8192,'size':len(self.encrypted)}
        (self.packs / 'basepack').unlink()
        with patch('webtools.core.model_faces._download_with_deadline', side_effect=HTTPError('https://x/basepack',404,'missing',{},None)), patch.object(game, '_metapack_download', return_value=bytes(self.encrypted)) as meta:
            self.assertEqual(Path(self.run_import(record).output_paths()[0]).read_bytes(), self.payload)
        args=meta.call_args.args;self.assertTrue(args[0].endswith('/metapack'));self.assertEqual(args[1:3],(8192,len(self.encrypted)))

    def test_untrusted_paths_variants_and_other_character_colours_rejected(self):
        for updates in [{'suit':'../../etc/passwd'}, {'region':'../../jp'}, {'variant':'unmasked'}, {'download':'yes'}, {'out_dir':'/tmp'}]:
            params={'region':'gl','suit':'suit:1','variant':'primary','download':False};params.update(updates)
            with self.assertRaises(ValueError):game.validate_selection(self.root,params)
        dbpath=self.root/'assets/db/gl/masterdata.db'
        with sqlite3.connect(dbpath) as db:db.execute("UPDATE m_suit_attach SET original_suit_master_id=2 WHERE suit_master_id=3")
        with self.assertRaisesRegex(ValueError,'does not match'):self.select('suit:3')

    def test_same_origin_http_api_and_strict_output_root(self):
        cwd=os.getcwd();os.chdir(self.root);self.addCleanup(os.chdir,cwd)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        base='http://127.0.0.1:'+str(server.server_port)
        with urlopen(base+'/api/viewer/game/catalog?region=gl&character=101&lang=ko') as response:
            self.assertEqual(response.status,200);self.assertEqual(json.load(response)['region'],'gl')
        request=Request(base+'/api/viewer/game/import',data=json.dumps({'region':'gl','suit':'suit:1','variant':'primary','download':False}).encode(),headers={'Content-Type':'application/json','Origin':'https://other.invalid'})
        with self.assertRaises(HTTPError) as rejected:urlopen(request)
        self.assertEqual(rejected.exception.code,403)
        request=Request(base+'/api/viewer/game/import',data=json.dumps({'region':'gl','suit':'suit:1','variant':'primary','download':False,'path':'/etc/passwd'}).encode(),headers={'Content-Type':'application/json','Origin':base})
        with self.assertRaises(HTTPError) as rejected:urlopen(request)
        self.assertEqual(rejected.exception.code,400)

    def test_metapack_range_headers_and_malformed_ranges(self):
        import io
        import time
        class Response:
            status=206
            headers={'Content-Range':'bytes 8-11/100','Content-Length':'4'}
            def __init__(self):self.body=io.BytesIO(b'abcd')
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def geturl(self):return 'https://example.invalid/meta'
            def read(self,size):return self.body.read(size)
        with patch('urllib.request.urlopen',side_effect=lambda request,timeout:Response()) as open_url:
            self.assertEqual(game._metapack_download('https://example.invalid/meta',8,4,time.monotonic()+2),b'abcd')
            self.assertEqual(open_url.call_args.args[0].get_header('Range'),'bytes=8-11')
        response=Response();response.headers={'Content-Range':'bytes 0-3/100','Content-Length':'4'}
        with patch('urllib.request.urlopen',return_value=response):
            with self.assertRaisesRegex(ValueError,'invalid package range'):
                game._metapack_download('https://example.invalid/meta',8,4,time.monotonic()+2)

    def test_real_selected_colour_composite_uses_only_the_authoritative_c1_texture(self):
        try:
            import UnityPy
            from PIL import Image
        except ImportError as error:
            self.skipTest(str(error))
        import struct
        fixture=(Path(__file__).parent/'fixtures/viewer_textured_triangle.unity').read_bytes()
        def scene(name,rgba):
            env=UnityPy.load(fixture)
            for obj in env.objects:
                if obj.type.name=='Texture2D':
                    data=obj.read();data.m_Name=name;data.m_TextureFormat=4
                    data.image=Image.new('RGBA',(2,2),rgba);data.save()
            return next(iter(env.files.values())).save()
        def bundle(entries):
            payload=b''.join(value for _,value in entries)
            info=bytes(16)+struct.pack('>iIIHi',1,len(payload),len(payload),0,len(entries))
            offset=0
            for name,value in entries:
                info+=struct.pack('>qqI',offset,len(value),0)+name.encode()+b'\0';offset+=len(value)
            prefix=b'UnityFS\0'+struct.pack('>I',6)+b'5.x.x\0'+b'2019.4.0f1\0'
            return prefix+struct.pack('>QIII',len(prefix)+20+len(info)+len(payload),len(info),len(info),64)+info+payload
        sources={'basepack':bundle([('base.assets',scene('Body',(0,0,255,255)))]),
                 'colourpack':bundle([('c1.assets',scene('Body_c1',(255,0,0,255))),('c2.assets',scene('Body_c2',(0,255,0,255)))])}
        for name,payload in sources.items():
            encrypted=bytearray(payload);extractor.decrypt_section(encrypted,extractor.FIXED_KEY0,7,11)
            (self.packs/name).write_bytes(encrypted)
            with sqlite3.connect(self.root/'assets/db/gl/asset_a_ko.db') as db:
                db.execute('UPDATE member_model SET size=? WHERE pack_name=?',(len(encrypted),name))
                db.execute('UPDATE m_asset_package_mapping SET file_size=? WHERE pack_name=?',(len(encrypted),name))
        before={name:hashlib.sha256((self.packs/name).read_bytes()).hexdigest() for name in sources}
        result=self.run_import(self.select('suit:3')).output_paths()
        self.assertEqual(len(result),1)
        textures=[obj.read() for obj in UnityPy.load(result[0]).objects if obj.type.name=='Texture2D']
        self.assertEqual(len(textures),1);self.assertEqual(textures[0].image.convert('RGBA').getpixel((0,0)),(255,0,0,255))
        for name,digest in before.items():self.assertEqual(hashlib.sha256((self.packs/name).read_bytes()).hexdigest(),digest)

    def test_existing_local_metapack_is_read_without_download_or_carving_files(self):
        (self.packs/'basepack').unlink()
        meta=self.packs/'metapack';meta.write_bytes(b'prefix!!'*1024+bytes(self.encrypted)+b'trailer')
        digest=hashlib.sha256(meta.read_bytes()).hexdigest()
        with sqlite3.connect(self.root/'assets/db/gl/asset_a_ko.db') as db:
            db.execute("UPDATE m_asset_package_mapping SET metapack_name='metapack',metapack_offset=8192 WHERE pack_name='basepack'")
        record=self.select()
        with patch('webtools.core.model_faces._download_with_deadline',side_effect=AssertionError('A cached metapack must remain offline')):
            output=self.run_import(record).output_paths()
            self.assertEqual(self.run_import(record).output_paths(),output)
        self.assertEqual(Path(output[0]).read_bytes(),self.payload)
        self.assertEqual(hashlib.sha256(meta.read_bytes()).hexdigest(),digest)
        self.assertFalse((self.packs/'basepack').exists())
        manifest=json.loads(next(self.output.glob('.selection-*.json')).read_text())
        self.assertEqual(manifest['source'][0]['pack_offset'],8192)

    def test_cancellation_during_real_decryption_cleans_staged_outputs(self):
        job=Job('during-decrypt','viewer_game_assets')
        decrypt=extractor.decrypt_section
        def stop_after_decrypt(*args):
            decrypt(*args);job.cancel_event.set()
        with patch.object(extractor,'decrypt_section',side_effect=stop_after_decrypt):
            self.run_import(job=job)
        self.assertEqual(job.output_paths(),[])
        self.assertFalse(list(self.output.glob('gl-*')))
        self.assertFalse(list(self.output.glob('*.part')))
