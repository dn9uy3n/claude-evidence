"""Render captured text (commands + output) to PNG "freeze" images.

Pure-Python (Pillow + Pygments) — no external `freeze` binary. Two coloring
paths: ANSI-SGR parsing for tool output that already carries colour (nmap,
sqlmap), and Pygments token colouring for everything else. Real screenshots are
not rendered here — they are embedded as-is by the report assembler.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from PIL import Image, ImageDraw, ImageFont
    from pygments import lex
    from pygments.lexers import BashSessionLexer, TextLexer
    from pygments.token import Token
    AVAILABLE = True
    IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - dependency probe
    AVAILABLE = False
    IMPORT_ERROR = exc


# --- theme ---------------------------------------------------------------

BG = (30, 30, 46)
PANEL = (24, 24, 37)
FG = (205, 214, 244)
DIM = (108, 112, 134)
BORDER = (69, 71, 90)

# Most-specific first. `subtype in type` is True for Pygments token subtypes.
_THEME = None


def _theme():
    global _THEME
    if _THEME is None:
        _THEME = [
            (Token.Comment, (108, 112, 134)),
            (Token.Keyword, (203, 166, 247)),
            (Token.Name.Builtin, (137, 180, 250)),
            (Token.Name.Function, (137, 180, 250)),
            (Token.Literal.String, (166, 227, 161)),
            (Token.Literal.Number, (250, 179, 135)),
            (Token.Operator, (137, 220, 235)),
            (Token.Generic.Prompt, (166, 227, 161)),
            (Token.Generic.Output, (205, 214, 244)),
            (Token.Generic.Error, (243, 139, 168)),
            (Token.Name, (205, 214, 244)),
        ]
    return _THEME


def _color_for(ttype):
    for t, c in _theme():
        if ttype in t:
            return c
    return FG


# --- ANSI SGR palette ----------------------------------------------------

_ANSI16 = {
    30: (88, 91, 112), 31: (243, 139, 168), 32: (166, 227, 161), 33: (249, 226, 175),
    34: (137, 180, 250), 35: (245, 194, 231), 36: (148, 226, 213), 37: (205, 214, 244),
    90: (127, 132, 156), 91: (243, 139, 168), 92: (166, 227, 161), 93: (249, 226, 175),
    94: (137, 180, 250), 95: (245, 194, 231), 96: (148, 226, 213), 97: (255, 255, 255),
}

_ANSI_RE = re.compile(r"\x1b\[([0-9;]*)m")


def _xterm256(n: int):
    if n < 16:
        return _ANSI16.get(30 + n if n < 8 else 82 + n, FG)
    if n >= 232:
        v = 8 + (n - 232) * 10
        return (v, v, v)
    n -= 16
    r = n // 36
    g = (n % 36) // 6
    b = n % 6
    conv = lambda c: 0 if c == 0 else 55 + c * 40
    return (conv(r), conv(g), conv(b))


def _ansi_lines(text: str):
    lines = [[]]
    cur = FG
    pos = 0
    for m in _ANSI_RE.finditer(text):
        chunk = text[pos:m.start()]
        _emit(lines, chunk, cur)
        cur = _apply_sgr(cur, m.group(1))
        pos = m.end()
    _emit(lines, text[pos:], cur)
    return lines


def _apply_sgr(cur, params):
    codes = [int(p) for p in params.split(";") if p != ""] or [0]
    i = 0
    while i < len(codes):
        c = codes[i]
        if c == 0:
            cur = FG
        elif c in _ANSI16:
            cur = _ANSI16[c]
        elif c == 39:
            cur = FG
        elif c == 38 and i + 1 < len(codes):
            if codes[i + 1] == 5 and i + 2 < len(codes):
                cur = _xterm256(codes[i + 2]); i += 2
            elif codes[i + 1] == 2 and i + 4 < len(codes):
                cur = (codes[i + 2], codes[i + 3], codes[i + 4]); i += 4
        i += 1
    return cur


def _emit(lines, chunk, color):
    if not chunk:
        return
    parts = chunk.split("\n")
    for idx, part in enumerate(parts):
        if idx > 0:
            lines.append([])
        if part:
            lines[-1].append((part, color))


# --- Pygments coloring ---------------------------------------------------

def _pygments_lines(text: str, mode: str):
    lexer = BashSessionLexer() if mode == "bash" else TextLexer()
    lines = [[]]
    for ttype, value in lex(text, lexer):
        color = _color_for(ttype)
        _emit_tokens(lines, value, color)
    return lines


def _emit_tokens(lines, value, color):
    parts = value.split("\n")
    for idx, part in enumerate(parts):
        if idx > 0:
            lines.append([])
        if part:
            lines[-1].append((part, color))


# --- font ----------------------------------------------------------------

def _load_font(config):
    names = (config.get("renderer") or {}).get("font") or ["Consolas", "DejaVu Sans Mono"]
    size = int((config.get("renderer") or {}).get("font_size", 15))
    candidates = []
    for n in names:
        candidates += [n, n + ".ttf", n.replace(" ", "") + ".ttf"]
    candidates += ["consola.ttf", "DejaVuSansMono.ttf", "cour.ttf"]
    for c in candidates:
        try:
            return ImageFont.truetype(c, size)
        except OSError:
            continue
    return ImageFont.load_default()


# --- draw ----------------------------------------------------------------

def render_text(text: str, dest: Path, config: dict, caption: str = "", mode: str = "plain") -> Path:
    if not AVAILABLE:
        raise RuntimeError(f"renderer dependencies missing: {IMPORT_ERROR}")

    max_lines = int((config.get("renderer") or {}).get("max_lines", 80))
    max_cols = 140

    if "\x1b[" in text:
        seg_lines = _ansi_lines(text)
    elif mode == "bash":
        seg_lines = _pygments_lines(text, "bash")
    else:
        seg_lines = _pygments_lines(text, "plain")

    truncated = len(seg_lines) > max_lines
    seg_lines = seg_lines[:max_lines]

    font = _load_font(config)
    ascent, descent = font.getmetrics()
    line_h = ascent + descent + 4
    try:
        char_w = font.getlength("M")
    except AttributeError:
        char_w = font.getbbox("M")[2]
    char_w = max(char_w, 1)

    pad = 20
    titlebar = 34
    cap_h = line_h + 6 if caption else 0

    # Truncate over-wide lines to bound image width.
    for li, segs in enumerate(seg_lines):
        total = sum(len(t) for t, _ in segs)
        if total > max_cols:
            budget = max_cols
            new = []
            for t, c in segs:
                if budget <= 0:
                    break
                if len(t) > budget:
                    new.append((t[:budget] + "…", c)); budget = 0
                else:
                    new.append((t, c)); budget -= len(t)
            seg_lines[li] = new

    content_cols = max((sum(len(t) for t, _ in segs) for segs in seg_lines), default=10)
    width = int(pad * 2 + max(content_cols, len(caption)) * char_w + 8)
    width = max(420, min(width, 1800))
    height = int(titlebar + cap_h + pad + max(len(seg_lines), 1) * line_h + pad)

    img = Image.new("RGB", (width, height), BG)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([1, 1, width - 2, height - 2], radius=10, outline=BORDER, width=1, fill=PANEL)
    # window buttons
    for i, col in enumerate([(243, 139, 168), (249, 226, 175), (166, 227, 161)]):
        d.ellipse([pad + i * 20, 12, pad + i * 20 + 12, 24], fill=col)
    if caption:
        d.text((pad, titlebar), caption[:200], font=font, fill=DIM)

    y = titlebar + cap_h + pad
    for segs in seg_lines:
        x = pad
        for t, color in segs:
            d.text((x, y), t, font=font, fill=color)
            try:
                x += font.getlength(t)
            except AttributeError:
                x += font.getbbox(t)[2]
        y += line_h

    if truncated:
        d.text((pad, height - line_h), "… (truncated — full text in steps/ file)", font=font, fill=DIM)

    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest)
    return dest


def render_step(session_dir: Path, record: dict, config: dict, dest: Path) -> Path | None:
    """Render one step's command/output PNG from its steps/ text file."""
    session_dir = Path(session_dir)
    text_path = record.get("text_path")
    if not text_path:
        return None
    src = session_dir / text_path
    if not src.exists():
        return None
    body = src.read_text(encoding="utf-8", errors="replace")
    body = body.split("\n--- raw tool_response", 1)[0].rstrip()
    seq = record.get("seq")
    short = record.get("tool_name", "").split("__")[-1]
    caption = f"#{seq:04d}  {short}  ·  {record.get('ts', '')}"
    mode = "bash" if record.get("source") == "command" else "plain"
    return render_text(body, dest, config, caption=caption, mode=mode)
