import http.client
import os
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

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
    (tmp_path / "secret.png").write_bytes(b"private")
    return folder


def get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=1) as response:
        return response.read()


def request(preview: Preview, target: str, host: str | None = None, method: str = "GET"):
    """Sends target as is (below the token unless it starts with //) and returns the response."""
    port = preview.address[1]
    path = target[1:] if target.startswith("//") else urlsplit(preview.url).path + target
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
    try:
        conn.request(method, path, headers={"Host": host or f"127.0.0.1:{port}"})
        response = conn.getresponse()
        response.body = response.read()
        return response
    finally:
        conn.close()


def status(preview: Preview, target: str, host: str | None = None) -> int:
    return request(preview, target, host).status


def test_preview_binds_localhost(preview, site):
    preview.start(site)

    assert preview.address[0] == "127.0.0.1"
    assert preview.url.startswith(f"http://127.0.0.1:{preview.address[1]}/")


def test_preview_serves_files(preview, site):
    url, _ = preview.start(site)

    assert get(url + "hero.gif") == b"GIF89a"


def test_preview_url_carries_a_random_token(preview, site):
    url, _ = preview.start(site)
    preview.stop()
    again, _ = preview.start(site)

    token = urlsplit(url).path.strip("/")
    assert len(token) >= 20
    assert urlsplit(again).path.strip("/") != token


def test_preview_lists_the_folder(preview, site):
    url, _ = preview.start(site)

    assert b'href="hero.gif"' in get(url)


def test_preview_accepts_localhost_as_host(preview, site):
    preview.start(site)

    assert status(preview, "hero.gif", host=f"localhost:{preview.address[1]}") == 200


def test_preview_refuses_a_foreign_host(preview, site):
    preview.start(site)

    assert status(preview, "hero.gif", host="evil.example") == 403
    assert status(preview, "", host=f"evil.example:{preview.address[1]}") == 403


def test_preview_needs_the_token(preview, site):
    preview.start(site)

    assert status(preview, "//hero.gif") == 404
    assert status(preview, "//") == 404
    assert status(preview, "//wrongtoken/hero.gif") == 404


def test_preview_redirects_the_bare_token_to_the_listing(preview, site):
    preview.start(site)
    token = urlsplit(preview.url).path.rstrip("/")

    response = request(preview, "/" + token)

    assert response.status == 301
    assert response.getheader("Location") == token + "/"


def test_preview_sends_nosniff(preview, site):
    preview.start(site)

    assert request(preview, "hero.gif").getheader("X-Content-Type-Options") == "nosniff"


def test_preview_hides_dotfiles(preview, site):
    (site / ".env.png").write_bytes(b"x")
    (site / ".git").mkdir()
    (site / ".git" / "a.png").write_bytes(b"x")
    preview.start(site)

    assert status(preview, ".env.png") == 404
    assert status(preview, ".git/a.png") == 404
    assert status(preview, "%2egit/a.png") == 404
    assert b".env" not in request(preview, "").body
    assert b".git" not in request(preview, "").body


def test_preview_serves_only_export_formats(preview, site):
    (site / "notes.txt").write_text("private")
    (site / "page.html").write_text("<script></script>")
    preview.start(site)

    assert status(preview, "notes.txt") == 404
    assert status(preview, "page.html") == 404
    assert b"notes.txt" not in request(preview, "").body


def test_preview_serves_subfolders(preview, site):
    (site / "walk").mkdir()
    (site / "walk" / "w_1.png").write_bytes(b"png")
    preview.start(site)

    assert request(preview, "walk/w_1.png").body == b"png"
    assert b'href="walk/"' in request(preview, "").body


def test_preview_blocks_parent_paths(preview, site):
    preview.start(site)

    assert status(preview, "../secret.png") == 404
    assert status(preview, "%2e%2e/secret.png") == 404
    assert status(preview, str(site.parent / "secret.png")) == 404


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="needs symlinks")
def test_preview_blocks_symlinks_out_of_the_folder(preview, site):
    try:
        (site / "leak.png").symlink_to(site.parent / "secret.png")
    except OSError:
        pytest.skip("cannot create symlinks here")
    preview.start(site)

    assert status(preview, "leak.png") == 404
    assert b"leak.png" not in request(preview, "").body


def test_preview_refuses_writes(preview, site):
    preview.start(site)

    assert request(preview, "new.png", method="PUT").status == 501
    assert not (site / "new.png").exists()


def test_preview_writes_nothing_to_stdout(preview, site, capfd):
    url, _ = preview.start(site)
    get(url + "hero.gif")
    status(preview, "missing.png")
    status(preview, "hero.gif", host="evil.example")

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
