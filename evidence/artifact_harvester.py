"""Harvest real pixel artifacts (screenshots) produced by MCP tool calls.

Two response shapes are handled:
  * filepath  -- tool returns a path to an image on disk (e.g. Playwright
                 browser_take_screenshot) -> copy it in.
  * base64    -- tool returns an inline image content block (e.g. Windows-MCP
                 Screenshot) -> decode it.

Fully defensive: any failure returns None; the hook never breaks on a bad artifact.
"""

from __future__ import annotations

import base64
import binascii
import os
import re
import shutil
from fnmatch import fnmatch
from pathlib import Path

from evidence_core import sha256_file

_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")

# Extract path-like substrings ending in an image extension from free text
# (e.g. Playwright returns "...saved as C:\\path\\shot.png"). Ordered most- to
# least-specific: quoted, Windows drive path (allows spaces), POSIX path, bare token.
_EXT_ALT = r"(?:png|jpg|jpeg|webp|gif|bmp)"
_PATH_RES = [
    re.compile(r'["\']([^"\']+\.' + _EXT_ALT + r')["\']', re.IGNORECASE),
    re.compile(r'([A-Za-z]:\\[^\n"\']+?\.' + _EXT_ALT + r')', re.IGNORECASE),
    re.compile(r'(/[^\n"\':*?<>|]+?\.' + _EXT_ALT + r')', re.IGNORECASE),
    re.compile(r'(\S+\.' + _EXT_ALT + r')', re.IGNORECASE),
]

_MAGIC = {
    b"\x89PNG\r\n\x1a\n": ".png",
    b"\xff\xd8\xff": ".jpg",
    b"GIF87a": ".gif",
    b"GIF89a": ".gif",
    b"BM": ".bmp",
}


def _sniff_ext(head: bytes) -> str | None:
    for magic, ext in _MAGIC.items():
        if head.startswith(magic):
            return ext
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return ".webp"
    return None


def _walk(obj):
    """Yield every nested value (dicts and lists descended into)."""
    yield obj
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _walk(v)


def _mode_for_tool(tool_name: str, mapping: dict) -> str | None:
    if tool_name in mapping:
        return mapping[tool_name]
    for pat, mode in mapping.items():
        if ("*" in pat or "?" in pat) and fnmatch(tool_name, pat):
            return mode
    return None


# --- base64 detection ----------------------------------------------------

def _find_image_b64(obj):
    """Return (data_b64, ext) from the first image content block found.

    Handles both MCP ({"type":"image","data":..,"mimeType":..}) and Anthropic
    tool-result ({"type":"image","source":{"data":..,"media_type":..}}) shapes.
    """
    for node in _walk(obj):
        if not isinstance(node, dict):
            continue
        if node.get("type") == "image":
            src = node.get("source")
            if isinstance(src, dict) and src.get("data"):
                return src.get("data"), _ext_from_mime(src.get("media_type"))
            if node.get("data"):
                return node.get("data"), _ext_from_mime(node.get("mimeType") or node.get("media_type"))
    return None, None


def _ext_from_mime(mime) -> str:
    if not mime:
        return ".png"
    mime = str(mime).lower()
    if "jpeg" in mime or "jpg" in mime:
        return ".jpg"
    if "webp" in mime:
        return ".webp"
    if "gif" in mime:
        return ".gif"
    return ".png"


def _harvest_base64(tool_response, dest_base: Path):
    data_b64, ext = _find_image_b64(tool_response)
    if not data_b64:
        return None
    try:
        raw = base64.b64decode(data_b64, validate=False)
    except (binascii.Error, ValueError):
        return None
    if not raw:
        return None
    sniffed = _sniff_ext(raw[:16])
    if sniffed is None:
        return None  # not actually an image
    dest = dest_base.with_suffix(sniffed)
    with open(dest, "wb") as fh:
        fh.write(raw)
    return dest


# --- filepath detection --------------------------------------------------

def _path_candidates(text: str):
    """Yield candidate image paths embedded anywhere in a string."""
    stripped = text.strip().strip('"\'')
    if stripped.lower().endswith(_IMAGE_EXTS):
        yield stripped
    for rex in _PATH_RES:
        for m in rex.finditer(text):
            yield m.group(1)


def _find_image_path(obj):
    for node in _walk(obj):
        if not isinstance(node, str) or "." not in node:
            continue
        for candidate in _path_candidates(node):
            try:
                p = Path(candidate)
                if p.is_file():
                    return p
            except (OSError, ValueError):
                continue
    return None


def _harvest_filepath(tool_input, tool_response, dest_base: Path):
    # Prefer the response (actual saved file); fall back to the input filename.
    src = _find_image_path(tool_response) or _find_image_path(tool_input)
    if src is None:
        return None
    try:
        with open(src, "rb") as fh:
            head = fh.read(16)
    except OSError:
        return None
    ext = _sniff_ext(head) or src.suffix.lower() or ".png"
    dest = dest_base.with_suffix(ext)
    try:
        shutil.copyfile(src, dest)
    except OSError:
        return None
    return dest


# --- public entry --------------------------------------------------------

def harvest(tool_name, tool_input, tool_response, session_dir: Path, seq: int,
            tool_short: str, config: dict):
    """Return {artifact_path, artifact_kind, artifact_sha256} or None."""
    if not config.get("capture", {}).get("screenshots", True):
        return None

    mapping = config.get("image_producing_tools", {})
    mode = _mode_for_tool(tool_name, mapping) or "auto"

    artifacts_dir = Path(session_dir) / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    dest_base = artifacts_dir / f"{seq:04d}-{tool_short}"

    dest = None
    if mode in ("base64", "auto"):
        dest = _harvest_base64(tool_response, dest_base)
    if dest is None and mode in ("filepath", "auto"):
        dest = _harvest_filepath(tool_input, tool_response, dest_base)
    if dest is None:
        return None

    rel = os.path.relpath(dest, session_dir).replace("\\", "/")
    return {
        "artifact_path": rel,
        "artifact_kind": "real_screenshot",
        "artifact_sha256": sha256_file(dest),
    }
