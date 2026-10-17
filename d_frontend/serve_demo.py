"""Serve the website and explicitly allowed demo datasets without copying data."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import argparse
import json
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
DATASETS = {
    'real': ('real', 'Real-data run · 9 cells', 'Real-source development inference; model evaluation is unverified.'),
    'replay': ('role_a_replay', 'Real-data replay · 33 cells', 'Historical replay from Role A. Predictions and dispatches appear only when supplied for this dataset.'),
    'mock': ('.', 'Synthetic demo · 3 cells', 'Synthetic development fixtures; not measured model performance.'),
}
FILES = ('features.json', 'cells.geojson', 'risk.json', 'dispatch.json')


class DemoHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, demo_root, **kwargs):
        self.demo_root = Path(demo_root).resolve()
        super().__init__(*args, directory=str(ROOT / 'd_frontend'), **kwargs)

    def json_response(self, value, status=200):
        body = json.dumps(value, allow_nan=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = unquote(urlsplit(self.path).path)
        if path == '/demo/catalog.json':
            datasets = []
            for key, (folder, label, description) in DATASETS.items():
                directory = (self.demo_root / folder).resolve()
                if not directory.is_relative_to(self.demo_root):
                    continue
                if not all((directory / f).is_file() for f in FILES[:2]):
                    continue
                features = json.loads((directory / 'features.json').read_text(encoding='utf-8'))
                datasets.append({'id': key, 'label': label, 'description': description,
                                 'base': f'/demo/{key}/', 'files': [f for f in FILES if (directory / f).is_file()],
                                 'timestamps': sorted({row['ts'] for row in features}), 'cell_count': len({row['cell_id'] for row in features})})
            return self.json_response({'datasets': datasets})
        if path.startswith('/demo/'):
            parts = path.split('/')
            if len(parts) != 4 or parts[2] not in DATASETS or parts[3] not in FILES:
                return self.json_response({'error': 'Unknown demo resource'}, 404)
            directory = (self.demo_root / DATASETS[parts[2]][0]).resolve()
            target = (directory / parts[3]).resolve()
            if not target.is_relative_to(self.demo_root) or not target.is_file():
                return self.json_response({'error': 'Feed not available for this dataset'}, 404)
            try:
                return self.json_response(json.loads(target.read_text(encoding='utf-8')))
            except (OSError, ValueError):
                return self.json_response({'error': 'Feed could not be read'}, 500)
        # This server exposes only the frontend and four allowlisted files per dataset.
        if path.startswith('/data/'):
            return self.json_response({'error': 'Select a demo dataset'}, 404)
        return super().do_GET()


def make_server(demo_root=ROOT / 'data/demo', port=8001):
    return ThreadingHTTPServer(('127.0.0.1', port), partial(DemoHandler, demo_root=demo_root))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8001)
    args = parser.parse_args()
    with make_server(port=args.port) as server:
        print(f'Peatland website: http://127.0.0.1:{server.server_port} (data/demo datasets)', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
