"""Check dataset isolation, optional outputs and the HTTP allowlist."""
from http.client import HTTPConnection
import json
from pathlib import Path
import shutil
import tempfile
import threading
import unittest

from d_frontend.serve_demo import ROOT, make_server


class DemoServerTests(unittest.TestCase):
    def test_datasets_are_separate_and_private_files_are_not_served(self):
        with tempfile.TemporaryDirectory() as folder:
            demo = Path(folder)
            for destination in [demo, demo / 'real', demo / 'role_a_replay']:
                destination.mkdir(exist_ok=True)
                for filename in ['features.json', 'cells.geojson']:
                    shutil.copyfile(ROOT / 'd_frontend/mocks' / filename, destination / filename)
            shutil.copyfile(ROOT / 'd_frontend/mocks/risk.json', demo / 'risk.json')
            with make_server(demo, port=0) as server:
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                connection = HTTPConnection('127.0.0.1', server.server_port, timeout=5)
                def get(path):
                    connection.request('GET', path)
                    response = connection.getresponse()
                    return response.status, response.read()
                try:
                    code, body = get('/demo/catalog.json')
                    self.assertEqual(code, 200)
                    catalog = {row['id']: row for row in json.loads(body)['datasets']}
                    self.assertIn('risk.json', catalog['mock']['files'])
                    self.assertNotIn('risk.json', catalog['replay']['files'])
                    coverage = demo / 'role_a_real/regional_40'
                    coverage.mkdir(parents=True)
                    for name in ['features.json', 'cells.geojson']:
                        shutil.copyfile(ROOT / 'd_frontend/mocks' / name, coverage / name)
                    (coverage / 'build_status.json').write_text('{"state":"running"}')
                    self.assertEqual(next(row for row in json.loads(get('/demo/catalog.json')[1])['datasets'] if row['id'] == 'coverage')['cell_count'], 3)
                    (coverage / 'build_status.json').write_text('{"state":"complete"}')
                    self.assertIn('coverage', [row['id'] for row in json.loads(get('/demo/catalog.json')[1])['datasets']])
                    self.assertEqual(get('/demo/replay/features.json')[0], 200)
                    self.assertEqual(get('/demo/replay/risk.json')[0], 404)
                    for path in ['/demo/real/history.parquet', '/demo/real/../../.env', '/demo/real/%2e%2e/.env', '/data/risk.json', '/.git/config', '/data/raw/Indonesia_Peat_Lands.geojson']:
                        self.assertEqual(get(path)[0], 404, path)
                    self.assertEqual(get('/')[0], 200)
                finally:
                    connection.close()
                    server.shutdown()
                    thread.join(timeout=5)


if __name__ == '__main__':
    unittest.main()
