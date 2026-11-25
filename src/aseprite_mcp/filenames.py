import re
from collections.abc import Iterable

# Room for a "_NN" suffix and an extension within the usual 255-byte name limit.
MAX_STEM_BYTES = 100

_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_RESERVED = {"con", "prn", "aux", "nul", "conin$", "conout$"} | {
    f"{port}{n}" for port in ("com", "lpt") for n in [*"123456789", "\u00b9", "\u00b2", "\u00b3"]
}


def safe_stem(name: str, fallback: str = "layer") -> str:
    """A file name stem that is valid on Windows, macOS and Linux alike."""
    stem = _FORBIDDEN.sub("_", name).rstrip(". ")
    if stem.startswith("."):
        stem = "_" + stem[1:]
    encoded = stem.encode("utf-8")
    if len(encoded) > MAX_STEM_BYTES:
        stem = encoded[:MAX_STEM_BYTES].decode("utf-8", errors="ignore").rstrip(". ")
    if not stem:
        return fallback
    # Windows refuses these names with any extension after them, e.g. "nul.txt.png".
    if stem.split(".")[0].rstrip(" ").lower() in _RESERVED:
        stem = "_" + stem
    return stem


def unique_stems(stems: Iterable[str]) -> list[str]:
    """Number repeated stems (a, a_2, a_3); case is ignored, as Windows and macOS do."""
    stems = list(stems)
    taken = {s.casefold() for s in stems}
    used: set[str] = set()
    out = []
    for stem in stems:
        candidate, n = stem, 1
        # A numbered name never takes one that another entry has as its own name.
        while candidate.casefold() in used or (candidate != stem and candidate.casefold() in taken):
            n += 1
            candidate = f"{stem}_{n}"
        used.add(candidate.casefold())
        out.append(candidate)
    return out
