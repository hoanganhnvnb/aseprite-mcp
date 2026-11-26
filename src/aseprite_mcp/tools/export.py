import json
import os
import shutil
import tempfile
import time
import warnings
from pathlib import Path
from typing import Annotated, Any, Literal

from PIL import Image, UnidentifiedImageError
from pydantic import Field

from .. import server
from ..colors import color_rgba
from ..errors import ToolError
from ..filenames import safe_stem, unique_stems
from ..models import Color, Coord
from ..ops import run_op
from ..paths import resolve_path, same_file
from ..preview import preview
from ..ranges import FrameSpec
from ..runner import check_writable, replace_file, temp_sibling
from ._registry import SpritePath
from .layers import LayerRef
from .sprite import MAX_CANVAS

IMAGE_EXTENSIONS = ("bmp", "png", "qoi", "tga")
ANIMATED_EXTENSIONS = ("gif", "webp")
EXPORT_EXTENSIONS = tuple(sorted(IMAGE_EXTENSIONS + ANIMATED_EXTENSIONS))
MAX_SCALE = 32
# Pixels one export call may write, every frame counted.
MAX_EXPORT_PIXELS = 4096 * 4096 * 4
# import_image into an indexed sprite compares every colour it draws with every
# palette entry; this many comparisons take a few seconds.
MAX_PALETTE_WORK = 1 << 26
# Coarse file systems (FAT) store modification times in 2-second steps.
MTIME_SLACK = 2.0

Scale = Annotated[
    int, Field(ge=1, le=MAX_SCALE, description="Output pixels per sprite pixel (nearest)")
]
Overwrite = Annotated[bool, Field(description="Replace files that already exist")]


def _extension(path: Path, allowed: tuple[str, ...]) -> str:
    ext = path.suffix.lower().removeprefix(".")
    if ext not in allowed:
        shown = f"'.{ext}'" if ext else "no extension"
        raise ToolError(f"Cannot export {path.name} ({shown}); use one of: {', '.join(allowed)}")
    return ext


def _output(path: str) -> Path:
    final = resolve_path(path, server.get_settings(), must_exist=False)
    if not final.parent.is_dir():
        raise ToolError(f"Folder does not exist: {final.parent}")
    return final


def _check_target(final: Path, sprite: Path, overwrite: bool) -> None:
    if same_file(final, sprite):
        raise ToolError(f"{final} must be a different file than the sprite itself")
    if final.is_dir():
        raise ToolError(f"{final} is a folder")
    if final.exists() and not overwrite:
        raise ToolError(f"{final} already exists; pass overwrite=true to replace it")
    check_writable(final)


def _place(files: list[tuple[Path, Path]], sprite: Path, overwrite: bool) -> None:
    """Move rendered files to their final names, all or none.

    Every target is checked first and every file copied next to its target; only then
    are they renamed into place. On failure the copies and any target this call
    created are removed. A file replaced with overwrite=True cannot be brought back.
    """
    for _, final in files:
        _check_target(final, sprite, overwrite)
    staged: list[tuple[Path, Path]] = []
    created: list[Path] = []
    try:
        for source, final in files:
            tmp = temp_sibling(final)
            staged.append((tmp, final))
            shutil.copyfile(source, tmp)
        for tmp, final in staged:
            existed = final.exists()
            replace_file(tmp, final)
            if not existed:
                created.append(final)
    except BaseException:
        for tmp, _ in staged:
            tmp.unlink(missing_ok=True)
        for final in created:
            final.unlink(missing_ok=True)
        raise


def _check_written(files: list[Path], started: float) -> None:
    for final in files:
        try:
            fresh = final.stat().st_mtime >= started - MTIME_SLACK
        except OSError:
            fresh = False
        if not fresh:
            raise ToolError(f"Aseprite did not write {final}")


def _bytes(files: list[Path]) -> int:
    return sum(f.stat().st_size for f in files)


@server.mcp.tool()
async def export(
    path: SpritePath,
    output: Annotated[
        str, Field(description="Image file to write; the extension picks the format")
    ],
    frames: Annotated[
        FrameSpec | None,
        Field(description='Frames: a number, "1-4", "1-4,7" or "all"; default see below'),
    ] = None,
    tag: Annotated[str | None, Field(min_length=1, description="Export this tag's frames")] = None,
    layer: Annotated[
        LayerRef | None, Field(description="Export only this layer or group, shown alone")
    ] = None,
    scale: Scale = 1,
    background: Annotated[
        Color | None, Field(description="Colour behind transparent pixels; default none")
    ] = None,
    overwrite: Overwrite = False,
) -> dict[str, Any]:
    """Render the sprite to .png, .gif, .webp, .bmp, .tga or .qoi; the sprite is not changed.

    .gif and .webp hold an animation: by default every frame, with the frame durations
    (gif loops forever, alpha is 1-bit). The other formats hold one image: by default
    frame 1; when several frames are exported each goes to its own file named after
    the frame number, e.g. walk.png with frames "1-3" writes walk_1.png, walk_2.png
    and walk_3.png (no walk.png). Pass frames or tag, not both; a tag's frames are
    exported in order whatever its direction. Hidden layers are left out; with layer,
    only that layer (or group) is shown, even when it is hidden, with its opacity and
    blend mode. The output folder must exist; existing files are refused unless
    overwrite is true. Files are written completely or not at all. One call writes
    at most 67108864 pixels, all frames and the scale counted. Not available in
    batch. Returns the files written, the frames, the image size and total bytes.
    """
    settings = server.get_settings()
    sprite = resolve_path(path, settings, must_exist=True)
    final = _output(output)
    ext = _extension(final, EXPORT_EXTENSIONS)
    if frames is not None and tag is not None:
        raise ToolError("Pass frames or tag, not both")
    animated = ext in ANIMATED_EXTENSIONS
    if frames is None and tag is None:
        frames = "all" if animated else [1]
    if animated or (tag is None and frames != "all" and len(frames) == 1):
        _check_target(final, sprite, overwrite)

    started = time.time()
    with tempfile.TemporaryDirectory(prefix="aseprite-mcp-export-") as tmp:
        params = {
            "dir": tmp,
            "ext": ext,
            "animated": animated,
            "frames": None if tag is not None else frames,
            "tag": tag,
            "layer": layer,
            "scale": scale,
            "background": None if background is None else list(color_rgba(background)),
            "max_pixels": MAX_EXPORT_PIXELS,
        }
        result = await run_op(sprite, "export_frames", params, settings=settings, mutates=False)
        rendered = [Path(tmp) / name for name in result["files"]]
        if animated or len(rendered) == 1:
            targets = [final]
        else:
            targets = [final.with_name(f"{final.stem}_{n}{final.suffix}") for n in result["frames"]]
        _place(list(zip(rendered, targets, strict=True)), sprite, overwrite)
    _check_written(targets, started)
    return {
        "files": [str(t) for t in targets],
        "frames": result["frames"],
        "width": result["width"],
        "height": result["height"],
        "bytes": _bytes(targets),
    }


def _sheet_data(source: Path, image: Path, data: Path) -> None:
    """Checks the data file and points its meta.image at the image's final place."""
    try:
        content = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ToolError(f"Aseprite wrote an unreadable sprite sheet data file: {e}") from None
    if not isinstance(content, dict) or "frames" not in content or "meta" not in content:
        raise ToolError("Aseprite wrote sprite sheet data without frames or meta")
    content["meta"]["image"] = Path(os.path.relpath(image, data.parent)).as_posix()
    source.write_text(json.dumps(content, indent=1, ensure_ascii=False), encoding="utf-8")


@server.mcp.tool()
async def export_spritesheet(
    path: SpritePath,
    output: Annotated[str, Field(description="Sheet image: .png, .bmp, .tga or .qoi")],
    data_output: Annotated[
        str | None, Field(description="JSON file describing the frames; default none")
    ] = None,
    sheet_type: Annotated[
        Literal["horizontal", "vertical", "rows", "columns", "packed"],
        Field(
            description="Layout: one row, one column, a grid filled by rows or columns, or packed"
        ),
    ] = "horizontal",
    tag: Annotated[str | None, Field(min_length=1, description="Only this tag's frames")] = None,
    scale: Scale = 1,
    padding: Annotated[int, Field(ge=0, le=32, description="Pixels between frames")] = 0,
    data_format: Annotated[
        Literal["hash", "array"],
        Field(description="JSON frames as an object keyed by name, or a list"),
    ] = "hash",
    overwrite: Overwrite = False,
) -> dict[str, Any]:
    """Lay the frames out in one image with Aseprite's sprite sheet exporter.

    horizontal puts all frames in one row, vertical in one column, rows and columns
    make a grid, packed fits frames tightly. Hidden layers are left out. data_output
    gets Aseprite's JSON: frames (an object keyed by frame name for "hash", a list for
    "array"; frame names count from 0) with each frame's rectangle and duration, and
    meta with the image path (relative to the JSON file), size and tags. The sprite is
    not changed; existing files are refused unless overwrite is true. Not available
    in batch.
    """
    settings = server.get_settings()
    sprite = resolve_path(path, settings, must_exist=True)
    image = _output(output)
    ext = _extension(image, IMAGE_EXTENSIONS)
    _check_target(image, sprite, overwrite)
    data = None
    if data_output is not None:
        data = _output(data_output)
        if data.suffix.lower() != ".json":
            raise ToolError(f"data_output must be a .json file, not {data.name}")
        if same_file(data, image):
            raise ToolError("output and data_output must be different files")
        _check_target(data, sprite, overwrite)

    started = time.time()
    with tempfile.TemporaryDirectory(prefix="aseprite-mcp-sheet-") as tmp:
        texture = Path(tmp) / f"sheet.{ext}"
        params = {
            "texture": str(texture),
            "data": str(Path(tmp) / "sheet.json") if data is not None else None,
            "data_format": data_format,
            "sheet_type": sheet_type,
            "tag": tag,
            "scale": scale,
            "padding": padding,
            "max_pixels": MAX_EXPORT_PIXELS,
        }
        result = await run_op(sprite, "export_sheet", params, settings=settings, mutates=False)
        with Image.open(texture) as img:
            width, height = img.size
        files = [(texture, image)]
        if data is not None:
            _sheet_data(Path(params["data"]), image, data)
            files.append((Path(params["data"]), data))
        _place(files, sprite, overwrite)
    targets = [final for _, final in files]
    _check_written(targets, started)
    return {
        "files": [str(t) for t in targets],
        "frame_count": result["frame_count"],
        "width": width,
        "height": height,
        "bytes": _bytes(targets),
    }


@server.mcp.tool()
async def export_layers(
    path: SpritePath,
    output_dir: Annotated[str, Field(description="Folder for the PNG files; created when missing")],
    include_hidden: Annotated[bool, Field(description="Export hidden layers too")] = False,
    frame: Annotated[int, Field(ge=1, description="1-based frame to export")] = 1,
    overwrite: Overwrite = False,
) -> dict[str, Any]:
    """Write one canvas-sized PNG per layer of one frame; the sprite is not changed.

    Every layer that holds pixels is exported, layers inside groups too; groups
    themselves get no file. Each layer is shown alone with its opacity and blend
    mode. Files are named after the layer path ("arms/left" -> arms_left.png) with
    characters Windows does not allow replaced by _, reserved names such as CON
    prefixed with _, and _2, _3... added to repeated names. Hidden layers (or layers
    in hidden groups) are skipped and listed unless include_hidden is true. Existing
    files are refused unless overwrite is true. Not available in batch.
    """
    settings = server.get_settings()
    sprite = resolve_path(path, settings, must_exist=True)
    folder = resolve_path(output_dir, settings, must_exist=False)
    if folder.exists() and not folder.is_dir():
        raise ToolError(f"{folder} is not a folder")

    started = time.time()
    with tempfile.TemporaryDirectory(prefix="aseprite-mcp-layers-") as tmp:
        params = {"dir": tmp, "frame": frame, "include_hidden": include_hidden}
        result = await run_op(sprite, "export_layers", params, settings=settings, mutates=False)
        layers = result["layers"]
        stems = unique_stems(safe_stem(entry["layer"]) for entry in layers)
        targets = [folder / f"{stem}.png" for stem in stems]
        for final in targets:
            _check_target(final, sprite, overwrite)
        new_dirs = [d for d in (folder, *folder.parents) if not d.exists()]
        folder.mkdir(parents=True, exist_ok=True)
        try:
            _place(
                [(Path(tmp) / entry["file"], final) for entry, final in zip(layers, targets)],
                sprite,
                overwrite,
            )
        except BaseException:
            for made in new_dirs:
                try:
                    made.rmdir()
                except OSError:
                    break
            raise
    _check_written(targets, started)
    return {
        "frame": result["frame"],
        "files": [
            {"layer": entry["layer"], "file": str(final)} for entry, final in zip(layers, targets)
        ],
        "hidden": result["hidden"],
    }


def _load_rgba(source: Path, dest: Path) -> int:
    """Writes the first frame of any image Pillow reads to dest as an RGBA PNG.

    Returns the number of non-transparent pixels.
    """
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(source) as img:
                w, h = img.size
                if w > MAX_CANVAS or h > MAX_CANVAS:
                    raise ToolError(
                        f"{source.name} is {w}x{h}, larger than {MAX_CANVAS}x{MAX_CANVAS}"
                    )
                img.seek(0)
                rgba = img.convert("RGBA")
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ToolError(f"{source.name} is too large to import") from None
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError) as e:
        raise ToolError(f"{source} is not an image Pillow can read: {e}") from None
    rgba.save(dest, "PNG")
    return w * h - rgba.getchannel("A").histogram()[0]


@server.mcp.tool()
async def import_image(
    path: SpritePath,
    image: Annotated[
        str, Field(description="Image file to draw in (png, gif, bmp, jpg, webp, ...)")
    ],
    layer: LayerRef,
    frame: Annotated[int, Field(ge=1, description="1-based frame")] = 1,
    x: Annotated[Coord, Field(description="Canvas x of the image's left edge")] = 0,
    y: Annotated[Coord, Field(description="Canvas y of the image's top edge")] = 0,
) -> dict[str, Any]:
    """Draw an image file into a layer at (x, y), over the pixels already there.

    Transparent pixels of the image leave the layer as it is; a GIF gives its first
    frame. Parts outside the canvas are dropped: placed and clipped count the image's
    non-transparent pixels drawn and dropped. The cel is created or grown as needed
    (a linked cel is unlinked first). Indexed sprites get the nearest palette entry
    for each colour (partly transparent pixels become opaque), grayscale ones the
    luma. For indexed sprites, the number of different RGB colours drawn times the
    palette size may be at most 67108864 (reduce the colours of photo-like images
    first); nothing changes when it is more. Locked layers,
    groups and tilemap layers are refused. Images up to 4096x4096. Not available in
    batch.
    """
    settings = server.get_settings()
    sprite = resolve_path(path, settings, must_exist=True)
    source = resolve_path(image, settings, must_exist=True)
    if not source.is_file():
        raise ToolError(f"{source} is not a file")
    with tempfile.TemporaryDirectory(prefix="aseprite-mcp-import-") as tmp:
        converted = Path(tmp) / "image.png"
        opaque = _load_rgba(source, converted)
        params = {
            "image": str(converted),
            "opaque": opaque,
            "max_palette_work": MAX_PALETTE_WORK,
            "layer": layer,
            "frame": frame,
            "x": x,
            "y": y,
        }
        return await run_op(sprite, "import_image", params, settings=settings, mutates=True)


@server.mcp.tool()
def start_preview(
    directory: Annotated[str, Field(description="Folder to serve, e.g. where exports go")],
    port: Annotated[int, Field(ge=0, le=65535, description="0 picks a free port")] = 0,
) -> dict[str, Any]:
    """Serve a folder over HTTP on 127.0.0.1 so exported images can be opened in a browser.

    Export into the folder, then open the returned URL exactly as given: its first
    path segment is a secret token, and file URLs are the URL plus the file's path
    inside the folder (e.g. url + "walk.gif"). The URL itself lists the folder. Only
    this machine can connect, and only with 127.0.0.1 or localhost as the host name.
    Only .png, .gif, .webp, .bmp, .tga, .qoi and .json files are served; dotfiles,
    other files and anything outside the folder are not, and nothing can be
    uploaded. One preview runs at a time: starting it again for the same folder
    returns the running URL; for another folder call stop_preview first. The server
    stops when this program exits.
    """
    settings = server.get_settings()
    folder = resolve_path(directory, settings, must_exist=True)
    if not folder.is_dir():
        raise ToolError(f"{folder} is not a folder")
    url, started = preview.start(folder, port)
    return {"url": url, "directory": str(folder), "already_running": not started}


@server.mcp.tool()
def stop_preview() -> dict[str, Any]:
    """Stop the preview server; stopped is false when none was running."""
    return {"stopped": preview.stop()}
