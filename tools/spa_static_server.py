#!/usr/bin/env python3
"""
Minimal static-file server with React/SPA fallback.

Serves real files from a build directory and falls back to index.html for
extensionless routes so BrowserRouter deep links keep working in production.

Production hardening:
- gzip compression for large text assets when the client supports it
- immutable cache headers for fingerprinted static assets
- no-cache for the HTML shell so new deploys are discovered quickly
"""

from __future__ import annotations

import argparse
import gzip
import io
import mimetypes
import posixpath
from functools import lru_cache
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit


COMPRESSIBLE_SUFFIXES = {".css", ".html", ".js", ".json", ".map", ".svg", ".txt"}
IMMUTABLE_CACHE_HEADER = "public, max-age=31536000, immutable"
HTML_CACHE_HEADER = "no-cache"
DEFAULT_CACHE_HEADER = "public, max-age=300"
GZIP_MIN_BYTES = 1024


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", required=True, help="Static build directory to serve")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host")
    parser.add_argument("--port", type=int, default=3030, help="Bind port")
    return parser


class SPARequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, directory: str, **kwargs):
        self._cache_request_path = "/"
        self._translated_request_path = ""
        self._response_code = 200
        self._vary_accept_encoding = False
        super().__init__(*args, directory=directory, **kwargs)

    def send_head(self):
        if self._should_fallback_to_index():
            original_path = self.path
            self.path = "/index.html"
            self._cache_request_path = "/index.html"
            try:
                return self._send_head_with_optional_gzip()
            finally:
                self.path = original_path
        self._cache_request_path = self._normalized_request_path(self.path)
        return self._send_head_with_optional_gzip()

    def translate_path(self, path):
        alias = self._static_alias_path(path)
        if alias is not None:
            self._translated_request_path = alias
            return super().translate_path(alias)
        self._translated_request_path = ""
        return super().translate_path(path)

    def end_headers(self):
        self.send_header("Cache-Control", self._cache_control_for_request())
        if self._vary_accept_encoding:
            self.send_header("Vary", "Accept-Encoding")
        super().end_headers()

    def send_response(self, code, message=None):
        self._response_code = code
        super().send_response(code, message)

    def _send_head_with_optional_gzip(self):
        translated_path = Path(self.translate_path(self.path))
        if not translated_path.exists() or translated_path.is_dir():
            self._vary_accept_encoding = False
            return super().send_head()

        stat_result = translated_path.stat()
        use_gzip = self._should_serve_gzip(translated_path, stat_result.st_size)
        self._vary_accept_encoding = use_gzip
        if not use_gzip:
            return super().send_head()

        content = self._gzip_bytes(
            str(translated_path),
            stat_result.st_mtime_ns,
            stat_result.st_size,
        )
        content_type, encoding = mimetypes.guess_type(str(translated_path))
        if content_type is None:
            content_type = "application/octet-stream"

        self.send_response(200)
        self.send_header("Content-type", content_type)
        if encoding:
            self.send_header("Content-Encoding", encoding)
        self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Last-Modified", self.date_time_string(stat_result.st_mtime))
        self.end_headers()
        return io.BytesIO(content)

    def _should_fallback_to_index(self) -> bool:
        request_path = self._normalized_request_path(self.path)
        normalized = posixpath.normpath(unquote(request_path))

        if normalized in {"", "."}:
            normalized = "/"

        if normalized == "/":
            return False

        if Path(normalized).suffix:
            return False

        translated = Path(self.translate_path(request_path))
        return not translated.exists()

    def _should_serve_gzip(self, translated_path: Path, size_bytes: int) -> bool:
        if translated_path.suffix.lower() not in COMPRESSIBLE_SUFFIXES:
            return False
        if size_bytes < GZIP_MIN_BYTES:
            return False
        accepted_encodings = self.headers.get("Accept-Encoding", "")
        return "gzip" in accepted_encodings.lower()

    def _cache_control_for_request(self) -> str:
        request_path = self._translated_request_path or self._cache_request_path or "/"
        if self._response_code >= 400:
            return HTML_CACHE_HEADER
        if request_path in {"/", "/index.html"}:
            return HTML_CACHE_HEADER
        if request_path.startswith("/static/"):
            return IMMUTABLE_CACHE_HEADER
        return DEFAULT_CACHE_HEADER

    @staticmethod
    def _normalized_request_path(path: str) -> str:
        return urlsplit(path).path or "/"

    @staticmethod
    def _static_alias_path(path: str) -> str | None:
        request_path = SPARequestHandler._normalized_request_path(path)
        normalized = posixpath.normpath(unquote(request_path))
        if normalized in {"", "."}:
            normalized = "/"
        marker = "/static/"
        index = normalized.find(marker)
        if index <= 0:
            return None
        return normalized[index:]

    @staticmethod
    @lru_cache(maxsize=128)
    def _gzip_bytes(path_str: str, mtime_ns: int, size_bytes: int) -> bytes:
        del mtime_ns, size_bytes
        return gzip.compress(Path(path_str).read_bytes(), compresslevel=6, mtime=0)


def main() -> int:
    args = build_parser().parse_args()
    directory = Path(args.directory).resolve()
    if not directory.is_dir():
        raise SystemExit(f"Build directory not found: {directory}")

    handler = partial(SPARequestHandler, directory=str(directory))
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"Serving SPA build from {directory} on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
