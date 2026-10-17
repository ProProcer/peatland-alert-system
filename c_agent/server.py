"""HTTP server to serve dispatch data to frontend (simulated API endpoint)."""

from __future__ import annotations

import json
import os
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from c_agent.email import generate_batch_email_summary, generate_email_notification
from c_agent.social_media import generate_social_media_posts
from c_agent.summary import export_to_csv, generate_summary, generate_risk_distribution

DATA_DIR = Path(__file__).parent.parent / "data" / "demo"
DISPATCH_FILE = DATA_DIR / "dispatch.json"


class DispatchHandler(SimpleHTTPRequestHandler):
    """Custom handler to serve dispatch data and related endpoints."""
    
    def _set_headers(self, content_type: str = "application/json") -> None:
        self.send_response(200)
        self.send_header("Content-type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
    
    def _send_json(self, data: Any) -> None:
        self._set_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))
    
    def _send_error(self, message: str, status: int = 404) -> None:
        self.send_response(status)
        self.send_header("Content-type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps({"error": message}).encode("utf-8"))
    
    def _load_dispatches(self) -> list[dict[str, Any]]:
        if not DISPATCH_FILE.exists():
            return []
        return json.loads(DISPATCH_FILE.read_text(encoding="utf-8"))
    
    def do_GET(self) -> None:
        """Handle GET requests."""
        parsed = urlparse(self.path)
        path = parsed.path
        
        # Serve static files from d_frontend
        if path == "/" or path == "/index.html":
            frontend_path = Path(__file__).parent.parent / "d_frontend" / "index.html"
            if frontend_path.exists():
                self._set_headers("text/html")
                self.wfile.write(frontend_path.read_bytes())
                return
            else:
                self._send_error("Frontend not found", 404)
                return
        
        # API endpoints
        if path == "/api/dispatch":
            dispatches = self._load_dispatches()
            self._send_json(dispatches)
            return
        
        if path == "/api/summary":
            dispatches = self._load_dispatches()
            summary = generate_summary(dispatches)
            self._send_json(summary)
            return
        
        if path == "/api/risk-distribution":
            dispatches = self._load_dispatches()
            distribution = generate_risk_distribution(dispatches)
            self._send_json(distribution)
            return
        
        if path == "/api/social-media":
            dispatches = self._load_dispatches()
            posts = generate_social_media_posts(dispatches)
            self._send_json(posts)
            return
        
        if path == "/api/email-summary":
            dispatches = self._load_dispatches()
            summary = generate_batch_email_summary(dispatches)
            self._send_json(summary)
            return
        
        if path == "/api/timeline":
            dispatches = self._load_dispatches()
            from c_agent.summary import generate_incident_timeline
            timeline = generate_incident_timeline(dispatches)
            self._send_json(timeline)
            return
        
        # Default: 404
        self._send_error("Endpoint not found", 404)
    
    def log_message(self, format: str, *args: Any) -> None:
        """Suppress default logging for cleaner output."""
        pass


def run_server(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Start the HTTP server."""
    server_address = (host, port)
    httpd = HTTPServer(server_address, DispatchHandler)
    print(f"C: HTTP server running at http://{host}:{port}")
    print(f"C: Endpoints:")
    print(f"C:   /              - Frontend (if d_frontend/index.html exists)")
    print(f"C:   /api/dispatch  - Dispatch data")
    print(f"C:   /api/summary   - Summary statistics")
    print(f"C:   /api/risk-distribution - Risk level distribution")
    print(f"C:   /api/social-media - Social media posts")
    print(f"C:   /api/email-summary - Email summary")
    print(f"C:   /api/timeline  - Incident timeline")
    print(f"C: Press Ctrl+C to stop")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nC: Server stopped")
        httpd.server_close()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind to")
    args = parser.parse_args()
    
    run_server(args.host, args.port)
