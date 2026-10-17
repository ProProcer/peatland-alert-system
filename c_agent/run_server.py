"""Standalone script to run the HTTP server for frontend integration."""

from c_agent.server import run_server

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Run HTTP server for dispatch data")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind to")
    args = parser.parse_args()
    
    run_server(args.host, args.port)
