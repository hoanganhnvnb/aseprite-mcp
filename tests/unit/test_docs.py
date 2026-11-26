import importlib.util
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "aseprite_mcp"

FENCE = re.compile(r"^```.*?^```", re.DOTALL | re.MULTILINE)
COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
INLINE_CODE = re.compile(r"`([^`\n]+)`")
LINK = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)\)")
HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$", re.MULTILINE)
HTML_SRC = re.compile(r"""(?:src|href)=["']([^"']+)["']""")
ENV_VAR = re.compile(r"ASEPRITE_[A-Z0-9]+(?:_[A-Z0-9]+)*")
TOOL_LIKE = re.compile(r"[a-z]+(?:_[a-z]+)+")

# Words that must not appear in anything tracked; written in pieces so this file is clean.
FORBIDDEN = ["cla" + "ude", "anthro" + "pic", "dii" + "vi", "divy" + "ansh", "up" + "stream"]


def _load_generator():
    spec = importlib.util.spec_from_file_location(
        "gen_tool_docs", ROOT / "scripts" / "gen_tool_docs.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def generator():
    return _load_generator()


def doc_files() -> list[Path]:
    files = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]
    files += [ROOT / "CONTRIBUTING.md", ROOT / "SECURITY.md", ROOT / "CHANGELOG.md"]
    return files


def tracked_files() -> list[Path]:
    git = shutil.which("git")
    if git is None:
        pytest.skip("git is not available")
    result = subprocess.run([git, "ls-files", "-z"], cwd=ROOT, capture_output=True, check=False)
    if result.returncode != 0:
        pytest.skip("not a git checkout")
    names = [n for n in result.stdout.decode("utf-8").split("\0") if n]
    return [ROOT / n for n in names]


def prose(path: Path) -> str:
    """The markdown without comments and fenced code blocks."""
    text = path.read_text(encoding="utf-8")
    return FENCE.sub("", COMMENT.sub("", text))


def test_tools_reference_matches_the_generator(generator):
    current = (ROOT / "docs" / "tools.md").read_text(encoding="utf-8").replace("\r\n", "\n")

    assert current == generator.render()


def test_tools_reference_says_it_is_generated():
    first_line = (ROOT / "docs" / "tools.md").read_text(encoding="utf-8").splitlines()[0]

    assert "Generated" in first_line
    assert "scripts/gen_tool_docs.py" in first_line


def test_tools_reference_lists_every_tool(generator):
    text = (ROOT / "docs" / "tools.md").read_text(encoding="utf-8")

    for tool in generator._tools():
        assert f"### `{tool.name}`" in text


def test_tools_reference_marks_batchable_and_read_only_tools():
    text = (ROOT / "docs" / "tools.md").read_text(encoding="utf-8")
    section = text.split("### `get_sprite_info`")[1].split("###")[0]
    create = text.split("### `create_sprite`")[1].split("###")[0]

    assert "batchable · read-only" in section
    assert "batchable" not in create


def known_names(generator) -> set[str]:
    """Tool names plus parameter names, which are snake_case too."""
    tools = generator._tools()
    names = {tool.name for tool in tools} | {"aseprite_mcp"}
    for tool in tools:
        names.update(tool.inputSchema.get("properties", {}))
        for definition in tool.inputSchema.get("$defs", {}).values():
            names.update(definition.get("properties", {}))
    return names


def unknown_tool_names(text: str, known: set[str]) -> list[str]:
    return [t for t in INLINE_CODE.findall(text) if TOOL_LIKE.fullmatch(t) and t not in known]


def test_backticked_tool_names_exist(generator):
    known = known_names(generator)

    unknown = []
    for path in doc_files():
        unknown += [
            f"{path.relative_to(ROOT)}: {t}" for t in unknown_tool_names(prose(path), known)
        ]

    assert unknown == []


def test_a_made_up_tool_name_is_reported(generator):
    known = known_names(generator)

    assert unknown_tool_names("Use `draw_circle` or `draw_rect`.", known) == ["draw_circle"]


def source_env_vars() -> set[str]:
    found: set[str] = set()
    for path in SRC.rglob("*.py"):
        found.update(re.findall(r'"(ASEPRITE_[A-Z0-9_]+)"', path.read_text(encoding="utf-8")))
    return found


def test_env_vars_in_docs_exist_in_the_code():
    known = source_env_vars()

    unknown = []
    for path in doc_files():
        for name in ENV_VAR.findall(path.read_text(encoding="utf-8")):
            if name not in known:
                unknown.append(f"{path.relative_to(ROOT)}: {name}")

    assert unknown == []


def test_every_env_var_in_the_code_is_in_configuration_md():
    text = (ROOT / "docs" / "configuration.md").read_text(encoding="utf-8")

    missing = [name for name in sorted(source_env_vars()) if f"`{name}`" not in text]

    assert missing == []


def link_targets(path: Path) -> list[str]:
    text = COMMENT.sub("", path.read_text(encoding="utf-8"))
    text = FENCE.sub("", text)
    return LINK.findall(text) + HTML_SRC.findall(text)


def slugify(heading: str) -> str:
    """GitHub's anchor for a heading: lower case, no punctuation, spaces become hyphens."""
    text = heading.replace("`", "").lower()
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def anchors(path: Path) -> set[str]:
    found: set[str] = set()
    seen: dict[str, int] = {}
    for heading in HEADING.findall(FENCE.sub("", path.read_text(encoding="utf-8"))):
        slug = slugify(heading)
        count = seen.get(slug, 0)
        seen[slug] = count + 1
        found.add(slug if count == 0 else f"{slug}-{count}")
    return found


def broken_links(path: Path) -> list[str]:
    broken = []
    for target in link_targets(path):
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        relative, _, fragment = target.partition("#")
        linked = path if not relative else path.parent / relative
        missing = not linked.exists()
        bad_anchor = bool(fragment) and linked.suffix == ".md" and fragment not in anchors(linked)
        if missing or bad_anchor:
            broken.append(target)
    return broken


def test_relative_links_images_and_anchors_resolve():
    broken = []
    for path in doc_files():
        broken += [f"{path.relative_to(ROOT)}: {t}" for t in broken_links(path)]

    assert broken == []


def test_a_link_to_a_missing_heading_is_reported(tmp_path):
    page = tmp_path / "page.md"
    page.write_text("# Title\n\n## Two words\n\n[ok](#two-words) [bad](#nope)\n", encoding="utf-8")

    assert broken_links(page) == ["#nope"]


def test_slugs_follow_github():
    assert slugify("Regions and transforms") == "regions-and-transforms"
    assert slugify("`run_lua`") == "run_lua"
    assert slugify("Export and import") == "export-and-import"


def test_the_link_scan_sees_links_in_the_readme():
    targets = link_targets(ROOT / "README.md")

    assert "docs/tools.md#sprite" in targets
    assert "LICENSE" in targets


def test_commented_out_images_are_not_checked(tmp_path):
    page = tmp_path / "page.md"
    page.write_text('<!-- showcase -->\n<!-- <img src="missing.gif"> -->\n', encoding="utf-8")

    assert link_targets(page) == []


def test_tracked_files_do_not_use_forbidden_words():
    found = []
    for path in tracked_files():
        if path == Path(__file__).resolve() or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8").lower()
        except UnicodeDecodeError:
            continue
        for word in FORBIDDEN:
            if word in text:
                found.append(f"{path.relative_to(ROOT)}: {word}")

    assert found == []


def test_every_tools_module_has_a_group(generator):
    modules = {p.stem for p in (SRC / "tools").glob("*.py") if not p.name.startswith("_")}

    assert modules == set(generator.GROUPS)


def test_readme_tool_count_matches_the_registry(generator):
    default_tools = [t for t in generator._tools() if t.name != "run_lua"]
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    match = re.search(r"(\d+) tools, plus `run_lua`", readme)

    assert match is not None
    assert int(match.group(1)) == len(default_tools)
