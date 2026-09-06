#!/usr/bin/env python3
"""Serve apps/site against a sealed bundle's data, without resealing.

Templates, styles and JS come from apps/site; data, map vendor files and the V1
archive come from an existing sealed bundle.  Use it to iterate on the public
front end; the sealed release build remains the only deployable artifact.

    uv run python scripts/serve_site.py --bundle build/releases/v2-published --port 8790
"""

from __future__ import annotations

import argparse
import http.server
import json
import os
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "apps/site"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, default=ROOT / "build/releases/v2-published")
    parser.add_argument("--port", type=int, default=8790)
    args = parser.parse_args()
    bundle = args.bundle.resolve()
    release_id = json.loads((bundle / "data/v2/current.json").read_text())["release_id"]

    class Handler(http.server.SimpleHTTPRequestHandler):
        extensions_map = {
            **http.server.SimpleHTTPRequestHandler.extensions_map,
            ".wasm": "application/wasm",
            ".js": "text/javascript",
        }

        def translate_path(self, path: str) -> str:
            path = unquote(path.split("?", 1)[0].split("#", 1)[0])
            if path.endswith("/"):
                path += "index.html"
            relative = path.lstrip("/")
            if relative.startswith(("js/", "styles/", "vendor/")):
                return str(SOURCE / relative)
            template = SOURCE / "templates" / relative
            if template.is_file():
                return str(template)
            return str(bundle / relative)

        def do_GET(self) -> None:  # noqa: N802 - http.server API
            target = Path(self.translate_path(self.path))
            if target.is_file() and target.suffix == ".html" and SOURCE in target.parents:
                body = target.read_text().replace("__WBA_RELEASE_ID__", release_id).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            super().do_GET()

        def end_headers(self) -> None:
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            if os.environ.get("WBA_SERVE_VERBOSE"):
                super().log_message(format, *args)

    print(f"serving apps/site with data from {bundle} at http://127.0.0.1:{args.port}/")
    http.server.ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
