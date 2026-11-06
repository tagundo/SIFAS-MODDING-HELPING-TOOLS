"""Disposable catalogs/packs for the product game-picker browser test."""
import json
import os
import sys
from pathlib import Path
from http.server import ThreadingHTTPServer
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_game_models import GameModelTests, extractor
from webtools.server import Handler

original_index = extractor.build_pack_index
original_roots = extractor.build_pack_roots
fixture = GameModelTests('test_catalog_region_language_search_and_exact_suit_identity')
fixture.setUp()
# Exercise the actual extractor's index/root discovery in browser flows.
extractor.build_pack_index = original_index
extractor.build_pack_roots = original_roots
extractor.COPIED_PACKS_DIR = str(fixture.packs)
os.environ['LLAS_INDEX_CACHE_DIR'] = str(fixture.root / '.pack-index')
os.chdir(fixture.root)
server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
print(json.dumps({'url':'http://127.0.0.1:'+str(server.server_port),'root':str(fixture.root),'library':str(fixture.library)}), flush=True)
try:
    server.serve_forever()
finally:
    server.server_close()
    fixture.doCleanups()
