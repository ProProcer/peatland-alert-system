"""Serve Role D assets and four explicitly allowed handoff files."""

from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from contracts.validate import KINDS, ROOT


class HandoffHandler(SimpleHTTPRequestHandler):
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, ".geojson": "application/geo+json"}

    def __init__(self, *args, data_dir: Path, **kwargs):
        self.data_dir = data_dir.resolve()
        super().__init__(*args, directory=str(ROOT / "d_frontend"), **kwargs)

    def send_head(self):
        path = unquote(urlsplit(self.path).path)
        if path.startswith("/data/") and path not in {f"/data/{name}" for name in KINDS.values()}:
            self.send_error(404, "Unknown handoff file")
            return None
        return super().send_head()

    def translate_path(self, path: str) -> str:
        parsed = unquote(urlsplit(path).path)
        if parsed in {f"/data/{name}" for name in KINDS.values()}:
            return str(self.data_dir / parsed.removeprefix("/data/"))
        return super().translate_path(path)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def make_server(data_dir: Path, host: str = "127.0.0.1", port: int = 8000) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), partial(HandoffHandler, data_dir=data_dir))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data/demo")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    with make_server(args.data_dir, args.host, args.port) as server:
        print(f"Handoff viewer: http://{args.host}:{server.server_port}; data: {args.data_dir.resolve()}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
