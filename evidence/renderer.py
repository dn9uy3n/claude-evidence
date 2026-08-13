"""Render captured text (commands + output) to PNG "freeze" images.

Pure-Python (Pillow + Pygments) — no external `freeze` binary. Two coloring
paths: ANSI-SGR parsing for tool output that already carries colour (nmap,
sqlmap), and Pygments token colouring for everything else. Real screenshots are
not rendered here — they are embedded as-is by the report assembler.
"""

from __future__ import annotations

import json
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


# --- structured JSON -> Markdown table ------------------------------------
# Pure stdlib, no Pillow/Pygments dependency — works even when AVAILABLE is
# False. Tool-agnostic by design: any MCP response shaped as a list of
# records (HexStrike scan findings, RedTech query results, WireMCP
# conversations, ...) renders as a real table instead of a JSON dump.

def _is_content_block_list(data) -> bool:
    """MCP tool responses are typically [{"type": "text", "text": "..."}, ...] —
    a protocol envelope, not the structured data itself."""
    return isinstance(data, list) and bool(data) and all(
        isinstance(x, dict) and "type" in x for x in data
    )


def _unwrap_mcp_content(data):
    """If `data` is an MCP content-block list, pull the real structured data out
    of its text block(s) (the tool's JSON is usually JSON-encoded as a string
    inside `text`, not a nested object). Returns None if it's an envelope with
    no parseable structured text (i.e. plain prose output — not tabular).
    Passes non-envelope data through unchanged.
    """
    if not _is_content_block_list(data):
        return data
    for block in data:
        if block.get("type") == "text" and isinstance(block.get("text"), str):
            try:
                return json.loads(block["text"])
            except (json.JSONDecodeError, TypeError):
                continue
    return None


def _table_rows(data):
    """Return the list-of-dict to tabulate, or None if `data` isn't tabular."""
    if isinstance(data, list) and data and all(isinstance(x, dict) for x in data):
        return data
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
                return v
    return None


def _table_cell(value, max_len=100) -> str:
    s = "" if value is None else str(value)
    s = s.replace("\n", " ⏎ ").replace("|", "\\|")
    return (s[: max_len - 1] + "…") if len(s) > max_len else s


def to_table(data, max_rows: int = 40, max_cols: int = 8) -> str | None:
    """Render `data` as a Markdown table if it's list-of-dict shaped, else None."""
    data = _unwrap_mcp_content(data)
    if data is None:
        return None
    rows = _table_rows(data)
    if not rows:
        return None
    cols = []
    for r in rows[:max_rows]:
        for k in r.keys():
            if k not in cols:
                cols.append(k)
    if not cols:
        return None
    cols = cols[:max_cols]

    lines = [
        "| " + " | ".join(cols) + " |",
        "|" + "|".join("---" for _ in cols) + "|",
    ]
    for r in rows[:max_rows]:
        lines.append("| " + " | ".join(_table_cell(r.get(c)) for c in cols) + " |")
    if len(rows) > max_rows:
        lines.append(f"\n_...{len(rows) - max_rows} more rows, see the raw JSON sidecar._")
    return "\n".join(lines)


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

_MAX_JSON_STRING = 300


def _clip_json_strings(obj):
    """Recursively clip long string values (e.g. a multi-KB SQL debug string
    in a "query" field) before pretty-printing. Without this, one verbose
    field wraps into dozens of image rows and eats the whole max_lines
    budget, silently pushing the OTHER fields — often the actual result data
    — out of the image entirely. Only affects this rendered view; the raw
    JSON sidecar / steps/*.txt keep the full, unclipped value."""
    if isinstance(obj, str):
        if len(obj) > _MAX_JSON_STRING:
            return obj[:_MAX_JSON_STRING] + f"… <{len(obj) - _MAX_JSON_STRING} more chars, see steps/ file>"
        return obj
    if isinstance(obj, dict):
        return {k: _clip_json_strings(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clip_json_strings(v) for v in obj]
    return obj


def _prettify_embedded_json(line: str):
    """If `line` contains a JSON object/array (a curl -d '{...}' payload, a raw
    JSON API response, ...), return the line with that JSON pretty-printed
    (one field per line) — the field a reviewer actually needs is then its own
    line instead of buried mid-way through a character-wrapped wall of text.
    Text before/after the JSON (e.g. `-d '` / `'`) is preserved as-is. Returns
    None if no JSON is found or it doesn't parse (left untouched — never
    guess wrong and corrupt what's shown)."""
    start = line.find("{")
    alt = line.find("[")
    if alt != -1 and (start == -1 or alt < start):
        start = alt
    if start == -1:
        return None
    end = max(line.rfind("}"), line.rfind("]"))
    if end == -1 or end <= start:
        return None
    try:
        parsed = json.loads(line[start:end + 1])
    except (json.JSONDecodeError, ValueError):
        return None
    pretty = json.dumps(_clip_json_strings(parsed), indent=2, ensure_ascii=False)
    return line[:start] + pretty + line[end + 1:]


def _prettify_json_lines(text: str) -> str:
    """Apply _prettify_embedded_json line-by-line across a whole text block."""
    return "\n".join(
        (_prettify_embedded_json(line) or line) for line in text.split("\n")
    )


def _wrap_segments(segs, max_cols: int):
    """Wrap one logical line's colored (text, color) fragments onto multiple
    display lines of at most max_cols characters each, splitting fragments as
    needed. Unlike truncation, this never drops any character."""
    lines = [[]]
    col = 0
    for text, color in segs:
        while text:
            remaining = max_cols - col
            if remaining <= 0:
                lines.append([])
                col = 0
                remaining = max_cols
            if len(text) <= remaining:
                lines[-1].append((text, color))
                col += len(text)
                text = ""
            else:
                lines[-1].append((text[:remaining], color))
                text = text[remaining:]
                lines.append([])
                col = 0
    return lines


def render_text(text: str, dest: Path, config: dict, caption: str = "", mode: str = "plain") -> Path:
    if not AVAILABLE:
        raise RuntimeError(f"renderer dependencies missing: {IMPORT_ERROR}")

    max_lines = int((config.get("renderer") or {}).get("max_lines", 80))
    max_cols = 140

    has_ansi = "\x1b[" in text
    if not has_ansi:
        # Pretty-print any embedded JSON (curl -d payloads, raw API responses)
        # BEFORE tokenizing -- one field per line reads far better than a
        # character-wrapped wall of compact JSON. Skipped for ANSI-colored
        # text to avoid the transform interacting with escape sequences.
        text = _prettify_json_lines(text)

    if has_ansi:
        seg_lines = _ansi_lines(text)
    elif mode == "bash":
        seg_lines = _pygments_lines(text, "bash")
    else:
        seg_lines = _pygments_lines(text, "plain")

    # Wrap (never truncate) lines wider than max_cols -- a long curl -d JSON
    # payload or API response is common evidence, and silently cutting it
    # with "…" makes the image itself an incomplete/misleading record. Wrap
    # BEFORE the max_lines cap below so that cap (which does carry an
    # explicit truncation notice) is what limits overall image size, not a
    # silent per-line cut.
    seg_lines = [wrapped for segs in seg_lines
                 for wrapped in (_wrap_segments(segs, max_cols)
                                 if sum(len(t) for t, _ in segs) > max_cols else [segs])]

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


def _clean_step_body(body: str) -> str:
    """Turn the verbose steps/*.txt record into a clean terminal-style
    transcript for the rendered PNG. steps/*.txt is written for full,
    unredacted audit detail (metadata preamble, explicit section labels, empty
    sections included) -- correct there, but that same detail is either
    redundant with what the report already shows around the image (seq/tool/
    timestamp as heading+caption; MCP tool_input as its own fenced JSON block
    right above the image) or just clutter (an empty '--- stderr ---' label,
    a '# desc:' annotation no real terminal would show). This drops all of
    that, leaving either `$ command` + real output, or (for MCP) just the
    response -- nothing else touches steps/*.txt, which stays exactly as
    captured.
    """
    if body.startswith("# EVIDENCE STEP"):
        idx = body.find("\n\n")
        body = body[idx + 2:] if idx != -1 else body

    if body.startswith("$ "):
        # The command itself may span multiple lines (line-continuations,
        # heredocs, ...) -- don't assume "first line == whole command". Split
        # on the fixed "\n\n--- stdout ---" separator _render_step_text()
        # always inserts between the command/desc header and the output
        # sections instead; everything before it is the header, however many
        # lines it spans.
        so = body.find("\n\n--- stdout ---")
        header, rest = (body, "") if so == -1 else (body[:so], body[so + len("\n\n--- stdout ---"):])

        hlines = header.split("\n")
        if hlines and hlines[-1].startswith("# desc:"):
            hlines = hlines[:-1]
        cmd = "\n".join(hlines).rstrip("\n")

        stdout = stderr = ""
        if rest:
            se = rest.find("--- stderr ---")
            stdout, stderr = (rest, "") if se == -1 else (rest[:se], rest[se + len("--- stderr ---"):])
        parts = [cmd]
        if stdout.strip():
            parts.append(stdout.strip("\n"))
        if stderr.strip():
            parts.append(stderr.strip("\n"))
        return "\n\n".join(parts)

    if body.startswith("--- tool_input ---"):
        idx = body.find("--- tool_response ---")
        return body[idx + len("--- tool_response ---"):].strip("\n") if idx != -1 else body

    return body


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
    body = _clean_step_body(body)
    seq = record.get("seq")
    short = record.get("tool_name", "").split("__")[-1]
    caption = f"#{seq:08d}  {short}  ·  {record.get('ts', '')}"
    mode = "bash" if record.get("source") == "command" else "plain"
    return render_text(body, dest, config, caption=caption, mode=mode)
