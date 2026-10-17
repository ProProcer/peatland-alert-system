"""Serve the website and explicitly allowed demo datasets without copying data."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import argparse
import json
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
DATASETS = {
    'coverage': ('role_a_real/regional_40', 'Kalimantan - 40 cells', 'Real-source historical snapshot. Predictions and dispatches appear only when supplied for this dataset.'),
    'real': ('real', 'Real-data run · 9 cells', 'Real-source development inference; model evaluation is unverified.'),
    'replay': ('role_a_replay', 'Real-data replay · 33 cells', 'Historical replay from Role A. Predictions and dispatches appear only when supplied for this dataset.'),
    'mock': ('.', 'Synthetic demo · 3 cells', 'Synthetic development fixtures; not measured model performance.'),
}
FILES = ('features.json', 'cells.geojson', 'risk.json', 'dispatch.json')


class DemoHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, demo_root, live_root=None, refresh_callback=None, **kwargs):
        self.demo_root = Path(demo_root).resolve()
        self.live_root = Path(live_root).resolve() if live_root is not None else None
        self.refresh_callback = refresh_callback
        super().__init__(*args, directory=str(ROOT / 'd_frontend'), **kwargs)

    def live_directory(self):
        if self.live_root is None:
            return None
        from e_platform.live_service import current_snapshot
        return current_snapshot(self.live_root)

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
        if path == '/live/status':
            if self.live_root is None:
                return self.json_response({'state': 'disabled', 'snapshot': None})
            from e_platform.live_service import service_status
            return self.json_response(service_status(self.live_root))
        if path.startswith('/live/snapshots/'):
            # Immutable, generation-specific feed URLs prevent mixed snapshots
            # if a refresh commits between the browser's parallel requests.
            parts = path.split('/')
            if self.live_root is None or len(parts) != 5 or parts[4] not in FILES:
                return self.json_response({'error': 'Unknown live feed'}, 404)
            directory = (self.live_root / 'snapshots' / parts[3]).resolve()
            if (not directory.is_relative_to(self.live_root / 'snapshots')
                    or not (directory / 'pipeline_manifest.json').is_file()):
                return self.json_response({'error': 'Live snapshot unavailable'}, 404)
            target = directory / parts[4]
            if not target.is_file():
                return self.json_response({'error': 'Live feed unavailable'}, 404)
            return self.json_response(json.loads(target.read_text(encoding='utf-8')))
        if path == '/response/status':
            from d_frontend.response_api import response_bundle
            try:
                if self.live_root is not None:
                    generation = parse_qs(urlsplit(self.path).query).get('generation', [None])[0]
                    directory = self.live_directory()
                    if generation is not None:
                        requested = (self.live_root / 'snapshots' / generation).resolve()
                        if (not requested.is_relative_to(self.live_root / 'snapshots')
                                or not (requested / 'pipeline_manifest.json').is_file()):
                            return self.json_response({'error': 'Live response snapshot unavailable'}, 404)
                        directory = requested
                    if directory is None:
                        return self.json_response({'error': 'Waiting for the first complete live snapshot'}, 503)
                    bundle = response_bundle(directory,
                        state_path=directory / 'agent_state.json', log_path=directory / 'notifications.log',
                        water_sources=ROOT / 'data/demo/role_a_real/water_sources.geojson')
                    bundle['engine']['automatic'] = True
                    return self.json_response(bundle)
                return self.json_response(response_bundle(self.demo_root / DATASETS['coverage'][0]))
            except (ValueError, OSError):
                return self.json_response({'error': 'Response data is invalid or unreadable'}, 500)
        if path == '/demo/catalog.json':
            if self.live_root is not None:
                directory = self.live_directory()
                if directory is None:
                    return self.json_response({'mode': 'live', 'datasets': []})
                manifest = json.loads((directory / 'pipeline_manifest.json').read_text(encoding='utf-8'))
                return self.json_response({'mode': 'live', 'datasets': [{
                    'id': 'live', 'label': 'Live Kalimantan · 40 cells',
                    'description': 'Automatically refreshed live inputs; provisional modeled risk and simulated actions.',
                    'base': f'/live/snapshots/{directory.name}/', 'files': list(FILES),
                    'timestamps': [manifest['snapshot']], 'cell_count': manifest['cell_count'],
                    'generation': directory.name}]})
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

    def do_POST(self):
        if self.path not in ('/response/run', '/live/refresh'):
            return self.json_response({'error': 'Unknown operation'}, 404)
        if self.live_root is not None and self.path == '/response/run':
            return self.json_response({'error': 'Live responses run automatically with each validated snapshot.'}, 409)
        # Mutations are same-origin and JSON-only; no external notification endpoint exists.
        origin = self.headers.get('Origin')
        if origin and origin != f"http://{self.headers.get('Host')}":
            return self.json_response({'error': 'Cross-origin operation rejected'}, 403)
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            return self.json_response({'error': 'Expected JSON'}, 415)
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 4096:
                raise ValueError('Invalid request size')
            options = json.loads(self.rfile.read(size))
            if self.path == '/live/refresh':
                if self.live_root is None or self.refresh_callback is None:
                    return self.json_response({'error': 'Live refresh is unavailable in demo mode.'}, 409)
                if not self.refresh_callback():
                    return self.json_response({'error': 'A refresh is already running or queued.'}, 409)
                return self.json_response({'state': 'queued'}, 202)
            from d_frontend.response_api import run_response
            result = run_response(self.demo_root / DATASETS['coverage'][0], options)
            return self.json_response(result)
        except (ValueError, OSError, SystemExit) as exc:
            return self.json_response({'error': str(exc)}, 400)


def make_server(demo_root=ROOT / 'data/demo', port=8001, *, host='127.0.0.1', live_root=None, refresh_callback=None):
    return ThreadingHTTPServer((host, port), partial(DemoHandler, demo_root=demo_root, live_root=live_root,
                                                   refresh_callback=refresh_callback))


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
