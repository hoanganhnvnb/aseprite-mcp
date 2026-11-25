import http.client
import os
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path

import pytest

from aseprite_mcp import server
from aseprite_mcp.config import Settings
from aseprite_mcp.errors import ToolError
from aseprite_mcp.preview import Preview


@pytest.fixture
def preview():
    p = Preview()
    yield p
    p.stop()


@pytest.fixture
def site(tmp_path: Path) -> Path:
    folder = tmp_path / "site"
    folder.mkdir()
    (folder / "hero.gif").write_bytes(b"GIF89a")
    (tmp_path / "secret.txt").write_text("private")
    return folder


def get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=1) as response:
        return response.read()


def raw_status(port: int, target: str) -> int:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
    try:
        conn.request("GET", target)
        return conn.getresponse().status
    finally:
        conn.close()


def test_preview_binds_localhost(preview, site):
    preview.start(site)

    assert preview.address[0] == "127.0.0.1"
    assert preview.url == f"http://127.0.0.1:{preview.address[1]}/"


def test_preview_serves_files(preview, site):
    url, _ = preview.start(site)

    assert get(url + "hero.gif") == b"GIF89a"


def test_preview_lists_the_folder(preview, site):
    url, _ = preview.start(site)

    assert b"hero.gif" in get(url)


def test_preview_blocks_parent_paths(preview, site):
    preview.start(site)
    port = preview.address[1]

    assert raw_status(port, "/../secret.txt") == 404
    assert raw_status(port, "/%2e%2e/secret.txt") == 404
    assert raw_status(port, "/" + str(site.parent / "secret.txt")) == 404


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="needs symlinks")
def test_preview_blocks_symlinks_out_of_the_folder(preview, site):
    try:
        (site / "leak.txt").symlink_to(site.parent / "secret.txt")
    except OSError:
        pytest.skip("cannot create symlinks here")
    preview.start(site)

    assert raw_status(preview.address[1], "/leak.txt") == 404


def test_preview_refuses_writes(preview, site):
    preview.start(site)
    conn = http.client.HTTPConnection("127.0.0.1", preview.address[1], timeout=1)
    try:
        conn.request("PUT", "/new.txt", body=b"x")
        assert conn.getresponse().status == 501
    finally:
        conn.close()
    assert not (site / "new.txt").exists()


def test_preview_writes_nothing_to_stdout(preview, site, capfd):
    url, _ = preview.start(site)
    get(url + "hero.gif")
    raw_status(preview.address[1], "/missing.png")

    assert capfd.readouterr().out == ""


def test_preview_stop_idempotent(preview, site):
    preview.start(site)

    assert preview.stop() is True
    assert preview.stop() is False
    assert preview.url is None


def test_preview_stop_ends_the_thread(preview, site):
    preview.start(site)
    preview.stop()

    assert not any(t.name == "preview-server" for t in threading.enumerate())


def test_preview_start_again_on_same_folder_returns_running_server(preview, site):
    first, started = preview.start(site)

    again, started_again = preview.start(site)

    assert (started, started_again) == (True, False)
    assert again == first


def test_preview_start_on_another_folder_refused(preview, site, tmp_path):
    preview.start(site)
    other = tmp_path / "other"
    other.mkdir()

    with pytest.raises(ToolError, match="already serving"):
        preview.start(other)


def test_preview_restarts_after_stop(preview, site):
    preview.start(site)
    preview.stop()

    url, started = preview.start(site)

    assert started
    assert get(url + "hero.gif") == b"GIF89a"


def make_settings(root: Path, sandbox: bool) -> Settings:
    return Settings(
        aseprite=None,
        root=root,
        sandbox=sandbox,
        timeout=60.0,
        max_procs=1,
        allow_lua=False,
        max_read_pixels=65536,
    )


@pytest.fixture
def tool(monkeypatch, tmp_path):
    def use(sandbox: bool = False):
        monkeypatch.setattr(server, "get_settings", lambda: make_settings(tmp_path, sandbox))

        async def call(name: str, /, **args):
            _, structured = await server.mcp.call_tool(name, args)
            return structured

        return call

    yield use
    from aseprite_mcp.tools import export

    export.preview.stop()


async def test_start_preview_tool_returns_url(tool, site):
    call = tool()

    result = await call("start_preview", directory="site")

    assert result["url"].startswith("http://127.0.0.1:")
    assert result["directory"] == str(site)
    assert get(result["url"] + "hero.gif") == b"GIF89a"
    assert await call("stop_preview") == {"stopped": True}
    assert await call("stop_preview") == {"stopped": False}


async def test_start_preview_needs_a_folder(tool, site):
    call = tool()

    with pytest.raises(ToolError, match="is not a folder"):
        await call("start_preview", directory="site/hero.gif")


async def test_start_preview_needs_an_existing_folder(tool):
    call = tool()

    with pytest.raises(ToolError, match="File not found"):
        await call("start_preview", directory="nowhere")


async def test_start_preview_stays_inside_sandbox(tool, site):
    call = tool(sandbox=True)

    with pytest.raises(ToolError, match="outside the allowed root"):
        await call("start_preview", directory="..")


def test_running_preview_does_not_keep_the_process_alive(site):
    script = (
        "import sys; from pathlib import Path; from aseprite_mcp.preview import Preview; "
        "Preview().start(Path(sys.argv[1]))"
    )
    done = subprocess.run([sys.executable, "-c", script, str(site)], check=False, timeout=10)

    assert done.returncode == 0
