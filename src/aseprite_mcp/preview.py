import atexit
import hmac
import html
import io
import os
import secrets
import socketserver
import sys
import threading
import urllib.parse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .errors import ToolError

HOST = "127.0.0.1"
# Only what exports produce; everything else in the folder stays private.
SERVED_EXTENSIONS = frozenset({".png", ".gif", ".webp", ".bmp", ".tga", ".qoi", ".json"})


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    # On Windows SO_REUSEADDR would let another program bind the same port.
    allow_reuse_address = sys.platform != "win32"
    token = ""
    hosts: frozenset[str] = frozenset()

    def server_bind(self) -> None:
        # HTTPServer.server_bind looks up the host name, which can stall on DNS.
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]

    def handle_error(self, request: Any, client_address: Any) -> None:
        pass


class _Handler(SimpleHTTPRequestHandler):
    """Serves one folder read-only below a secret first path segment.

    A request needs a Host header naming this server (so a web page that rebinds its
    own domain to 127.0.0.1 is refused) and the token (so other local pages cannot
    guess URLs). Dotfiles, files of other types and anything outside the folder,
    symlinks included, answer 404.
    """

    server: _Server
    # A folder always gets the filtered listing. The base class would otherwise serve
    # its index.html, a file send_head never checked; with this off, the file it opens
    # is always the translated path send_head checked.
    index_pages = ()

    def _below_token(self, path: str) -> str | None:
        token, _, rest = urllib.parse.urlsplit(path).path.removeprefix("/").partition("/")
        if not hmac.compare_digest(token.encode(), self.server.token.encode()):
            return None
        return "/" + rest

    def translate_path(self, path: str) -> str:
        # send_head has refused requests without the token before this is used.
        return super().translate_path(self._below_token(path) or "/")

    def _allowed(self, target: str) -> bool:
        root = os.path.realpath(self.directory)
        real = os.path.realpath(target)
        if real == root:
            return True
        if not real.startswith(root.rstrip(os.sep) + os.sep):
            return False
        if any(part.startswith(".") for part in Path(os.path.relpath(real, root)).parts):
            return False
        return os.path.isdir(real) or Path(real).suffix.lower() in SERVED_EXTENSIONS

    def send_head(self) -> Any:
        if self.headers.get("Host", "") not in self.server.hosts:
            self.send_error(403, "Unknown host")
            return None
        rest = self._below_token(self.path)
        if rest is None:
            self.send_error(404, "File not found")
            return None
        names = urllib.parse.unquote(rest).split("/")
        target = self.translate_path(self.path)
        if any(name.startswith(".") for name in names) or not self._allowed(target):
            self.send_error(404, "File not found")
            return None
        return super().send_head()

    def list_directory(self, path: str | os.PathLike[str]) -> Any:
        try:
            entries = sorted(os.listdir(path), key=str.lower)
        except OSError:
            self.send_error(404, "File not found")
            return None
        links = []
        for name in entries:
            full = os.path.join(path, name)
            if name.startswith(".") or not self._allowed(full):
                continue
            shown = name + "/" if os.path.isdir(full) else name
            href = urllib.parse.quote(shown)
            links.append(f'<li><a href="{href}">{html.escape(shown)}</a></li>')
        items = "\n".join(links)
        body = (
            '<!DOCTYPE html>\n<html><head><meta charset="utf-8"><title>Preview</title></head>'
            f"<body><ul>\n{items}\n</ul></body></html>\n"
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        return io.BytesIO(body)

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    # stdout carries the MCP protocol and stderr is the client's log; stay silent.
    def log_message(self, format: str, *args: Any) -> None:
        pass


class Preview:
    """One HTTP server on 127.0.0.1 that shows a folder, run on a daemon thread."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._server: _Server | None = None
        self._thread: threading.Thread | None = None
        self._directory: Path | None = None

    @property
    def address(self) -> tuple[str, int] | None:
        server = self._server
        return None if server is None else server.server_address[:2]

    @property
    def url(self) -> str | None:
        server = self._server
        return None if server is None else _url(server)

    @property
    def directory(self) -> Path | None:
        return self._directory

    def start(self, directory: Path, port: int = 0) -> tuple[str, bool]:
        """Returns the URL and whether a new server was started."""
        if not directory.is_dir():
            raise ToolError(f"{directory} is not a folder")
        with self._lock:
            if self._server is not None:
                running = self._server.server_address[1]
                if self._directory == directory and port in (0, running):
                    return _url(self._server), False
                raise ToolError(
                    f"The preview is already serving {self._directory} at "
                    f"{_url(self._server)}; call stop_preview first"
                )
            handler = partial(_Handler, directory=str(directory))
            try:
                server = _Server((HOST, port), handler)
            except OSError as e:
                raise ToolError(f"Cannot listen on {HOST}:{port}: {e.strerror or e}") from None
            bound = server.server_address[1]
            server.token = secrets.token_urlsafe(16)
            server.hosts = frozenset({f"{HOST}:{bound}", f"localhost:{bound}"})
            thread = threading.Thread(
                target=server.serve_forever,
                kwargs={"poll_interval": 0.1},
                name="preview-server",
                daemon=True,
            )
            thread.start()
            self._server, self._thread, self._directory = server, thread, directory
            return _url(server), True

    def stop(self) -> bool:
        """Stops the server; False when none was running."""
        with self._lock:
            server, thread = self._server, self._thread
            if server is None or thread is None:
                return False
            self._server = self._thread = self._directory = None
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            return True


def _url(server: _Server) -> str:
    return f"http://{HOST}:{server.server_address[1]}/{server.token}/"


preview = Preview()
atexit.register(preview.stop)
