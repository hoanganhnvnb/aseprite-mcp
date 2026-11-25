import atexit
import os
import socketserver
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .errors import ToolError

HOST = "127.0.0.1"


class _Handler(SimpleHTTPRequestHandler):
    """Serves one folder read-only; nothing outside it, symlinks included."""

    def send_head(self) -> Any:
        root = os.path.realpath(self.directory)
        target = os.path.realpath(self.translate_path(self.path))
        if target != root and not target.startswith(root.rstrip(os.sep) + os.sep):
            self.send_error(404, "File not found")
            return None
        return super().send_head()

    # stdout carries the MCP protocol and stderr is the client's log; stay silent.
    def log_message(self, format: str, *args: Any) -> None:
        pass


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    # On Windows SO_REUSEADDR would let another program bind the same port.
    allow_reuse_address = sys.platform != "win32"

    def server_bind(self) -> None:
        # HTTPServer.server_bind looks up the host name, which can stall on DNS.
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]

    def handle_error(self, request: Any, client_address: Any) -> None:
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
        address = self.address
        return None if address is None else f"http://{address[0]}:{address[1]}/"

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
                    return f"http://{HOST}:{running}/", False
                raise ToolError(
                    f"The preview is already serving {self._directory} at "
                    f"http://{HOST}:{running}/; call stop_preview first"
                )
            handler = partial(_Handler, directory=str(directory))
            try:
                server = _Server((HOST, port), handler)
            except OSError as e:
                raise ToolError(f"Cannot listen on {HOST}:{port}: {e.strerror or e}") from None
            thread = threading.Thread(
                target=server.serve_forever,
                kwargs={"poll_interval": 0.1},
                name="preview-server",
                daemon=True,
            )
            thread.start()
            self._server, self._thread, self._directory = server, thread, directory
            return f"http://{HOST}:{server.server_address[1]}/", True

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


preview = Preview()
atexit.register(preview.stop)
