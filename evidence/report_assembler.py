"""Assemble a Markdown evidence report from log.jsonl + annotations.json.

Header carries engagement, time range, and the manifest / chain-head hash the
client can verify. Each step gets: the command (or MCP input), a note and ATT&CK
technique if annotated, and its main visual -- in priority order, a structured
table (for tabular MCP responses), else a harvested real screenshot (Playwright/
Windows-MCP/...) if one exists for the step, else a rendered PNG of the raw
output. A real screenshot is never regenerated as a PNG-of-text; it's shown as-is.

If Pillow/Pygments are unavailable the report still builds — output falls back to
text code fences instead of rendered PNGs.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evidence_core as core  # noqa: E402
import map_builder  # noqa: E402

try:
    import renderer
    _RENDER = renderer.AVAILABLE
except Exception:
    renderer = None
    _RENDER = False


def _annot(annotations, seq):
    raw = annotations.get(str(seq))
    if raw is None:
        return "", ""
    if isinstance(raw, dict):
        return raw.get("note", ""), raw.get("attack", "")
    return str(raw), ""


def _fence(text, lang=""):
    body = str(text).replace("```", "``​`")
    return f"```{lang}\n{body}\n```"


def build(session_dir: Path, config: dict, fmt: str = "md") -> Path:
    session_dir = Path(session_dir)
    config = config or {}
    records = map_builder._load_records(session_dir)
    annotations = core.load_json(session_dir / "annotations.json", default={}) or {}
    engagement = session_dir.parent.name
    session_id = session_dir.name

    report_dir = session_dir / "report"
    img_dir = report_dir / "img"
    img_dir.mkdir(parents=True, exist_ok=True)

    chain = core.verify_chain(session_dir)
    manifest = core.load_json(session_dir.parent / "manifest.json", default=None)
    head = core.read_head(session_dir)
    head_hash = head.get("record_sha256", core.GENESIS_HASH)
    shots = [r for r in records if r.get("artifact_path")]
    ts_first = records[0].get("ts", "") if records else ""
    ts_last = records[-1].get("ts", "") if records else ""

    out = []
    out.append(f"# Evidence Report — {engagement}")
    out.append("")
    out.append(f"- **Session:** `{session_id}`")
    out.append(f"- **Time range:** {ts_first} → {ts_last}")
    out.append(f"- **Steps:** {len(records)}  ·  **Screenshots:** {len(shots)}")
    out.append(f"- **Chain integrity:** {'✅ OK' if chain['ok'] else '❌ BROKEN at #' + str(chain['break_at'])}"
               f" ({chain['count']} records)")
    if manifest and manifest.get("final_record_sha256"):
        out.append(f"- **Manifest hash (sealed):** `{manifest['final_record_sha256']}`")
    else:
        out.append(f"- **Chain head hash (live):** `{head_hash}`")
    out.append("")
    out.append("> Raw source of truth: `log.jsonl` (append-only, hash-chained). "
               "Full per-step text in `steps/`. Real screenshots in `artifacts/`.")
    out.append("")
    out.append("---")
    out.append("")

    for r in records:
        seq = r.get("seq")
        short = r.get("tool_name", "").split("__")[-1]
        note, attack = _annot(annotations, seq)

        # Structured table takes priority for MCP responses shaped as records
        # (HexStrike scans, RedTech queries, ...) — tool-agnostic, no allowlist.
        table_md = None
        if renderer and r.get("source") == "mcp" and r.get("response_json_path"):
            try:
                resp_data = core.load_json(session_dir / r["response_json_path"], default=None)
                table_md = renderer.to_table(resp_data)
            except Exception:
                table_md = None

        tag = "  ·  📊 table" if table_md else ""
        out.append(f"## Step {seq:08d} — `{short}`  ({r.get('source')}){tag}")
        out.append(f"_{r.get('ts', '')}_")
        out.append("")
        if note or attack:
            label = (f"**ATT&CK {attack}** — " if attack else "") + (note or "")
            out.append(f"> {label}")
            out.append("")
        if r.get("sensitive_hint"):
            out.append("> ⚠️ This step's output may contain secrets/tokens/PII — review before the report leaves your hands.")
            out.append("")

        ti = r.get("tool_input") or {}
        if r.get("source") == "command" and isinstance(ti, dict) and ti.get("command"):
            out.append(_fence(ti.get("command"), "bash"))
        elif ti:
            out.append(_fence(json.dumps(ti, ensure_ascii=False, indent=2), "json"))
        out.append("")

        art = r.get("artifact_path")
        has_real_shot = bool(art) and r.get("artifact_kind") == "real_screenshot"

        if table_md:
            out.append(table_md)
            out.append("")
        elif has_real_shot:
            pass  # a real screenshot (Playwright/Windows-MCP/...) exists for this
            # step -- shown below; no point re-rendering a PNG from the step text.
        else:
            # rendered output PNG (or text fallback)
            png_ref = None
            if _RENDER:
                try:
                    dest = img_dir / f"{seq:08d}-step.png"
                    if renderer.render_step(session_dir, r, config, dest):
                        png_ref = f"img/{dest.name}"
                except Exception:
                    png_ref = None
            if png_ref:
                out.append(f"![step {seq:08d} output]({png_ref})")
            else:
                src = session_dir / (r.get("text_path") or "")
                if src.exists():
                    body = src.read_text(encoding="utf-8", errors="replace").split("\n--- raw tool_response", 1)[0]
                    out.append(_fence(body[:6000]))
            out.append("")

        if art:
            out.append(f"**Screenshot** (`{r.get('artifact_sha256', '')[:16]}…`):")
            out.append(f"![screenshot {seq:08d}](../{art})")
            out.append("")

        out.append(f"↳ raw: [`{r.get('text_path')}`](../{r.get('text_path')})")
        out.append("")
        out.append("---")
        out.append("")

    dest = report_dir / ("report.md" if fmt == "md" else f"report.{fmt}")
    dest.write_text("\n".join(out), encoding="utf-8")
    return dest


def main(argv=None):
    argv = argv or sys.argv[1:]
    ws = core.resolve_workspace()
    state = core.load_state(ws)
    session_dir = core.session_dir_from_state(state, ws)
    if session_dir is None:
        print("no active session", file=sys.stderr)
        return 1
    dest = build(session_dir, core.load_config(ws))
    print(dest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
