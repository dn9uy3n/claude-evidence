"""Generate map.md from log.jsonl + annotations.json.

Two sections: a screenshots pick-list (only steps with a real artifact) and the
full timeline. Tolerant of a partially-written trailing line (concurrent append).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evidence_core as core  # noqa: E402


def _cell(value, maxlen=90) -> str:
    s = str(value if value is not None else "")
    s = s.replace("\r", " ").replace("\n", " ⏎ ").replace("|", "\\|")
    if len(s) > maxlen:
        s = s[: maxlen - 1] + "…"
    return s


def _time_of(ts: str) -> str:
    if ts and "T" in ts:
        return ts.split("T", 1)[1][:8]
    return ts or ""


def _note_and_attack(annotations: dict, seq):
    raw = annotations.get(str(seq))
    if raw is None:
        return "", ""
    if isinstance(raw, dict):
        return raw.get("note", ""), raw.get("attack", "")
    return str(raw), ""


def _tool_label(rec: dict) -> str:
    warn = "⚠️ " if rec.get("sensitive_hint") else ""
    ti = rec.get("tool_input") or {}
    if rec.get("source") == "command" and isinstance(ti, dict) and ti.get("command"):
        return warn + "`" + _cell(ti.get("command"), 90) + "`"
    return warn + _cell(rec.get("tool_name", "").split("__")[-1], 70)


def _load_records(session_dir: Path):
    records = []
    log = session_dir / "log.jsonl"
    if not log.exists():
        return records
    with open(log, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # skip a partially-written trailing line
    return records


def build(session_dir: Path, config: dict | None = None) -> Path:
    session_dir = Path(session_dir)
    config = config or {}
    records = _load_records(session_dir)
    annotations = core.load_json(session_dir / "annotations.json", default={}) or {}

    engagement = session_dir.parent.name
    session_id = session_dir.name
    shots = [r for r in records if r.get("artifact_path")]

    out = []
    out.append(f"# Evidence Map — {engagement} — session {session_id}")
    out.append(f"_Auto-generated from log.jsonl (append-only). Updated: {core.utc_now_iso()}_")
    out.append("")
    out.append(f"**Steps:** {len(records)}  ·  **Screenshots:** {len(shots)}")
    out.append("")

    if (config.get("map") or {}).get("screenshots_section", True):
        out.append("## 📷 Ảnh chụp (chọn nhanh)")
        if shots:
            out.append("| # | Time | Tool | Ảnh | Ghi chú |")
            out.append("|------|----------|--------------------------|------------------------------|----------------------------|")
            for r in shots:
                note, attack = _note_and_attack(annotations, r.get("seq"))
                note_cell = _cell((f"[{attack}] " if attack else "") + note, 60)
                art = r.get("artifact_path")
                out.append(
                    f"| {r.get('seq'):08d} | {_time_of(r.get('ts', ''))} "
                    f"| {_cell(r.get('tool_name', '').split('__')[-1], 40)} "
                    f"| [{art}]({art}) | {note_cell} |"
                )
        else:
            out.append("_Chưa có ảnh nào được harvest._")
        out.append("")

    out.append("## 🧭 Toàn bộ timeline")
    out.append("| # | Time | Source | Tool / Lệnh | Text | Ảnh | Ghi chú |")
    out.append("|------|----------|--------|--------------------------|--------------------------|------------------------------|-----------|")
    for r in records:
        note, attack = _note_and_attack(annotations, r.get("seq"))
        note_cell = _cell((f"[{attack}] " if attack else "") + note, 40)
        text_path = r.get("text_path")
        text_cell = f"[{text_path}]({text_path})" if text_path else "—"
        art = r.get("artifact_path")
        art_cell = f"[{art}]({art})" if art else "—"
        out.append(
            f"| {r.get('seq'):08d} | {_time_of(r.get('ts', ''))} | {_cell(r.get('source'), 8)} "
            f"| {_tool_label(r)} | {text_cell} | {art_cell} | {note_cell} |"
        )
    out.append("")

    dest = session_dir / "map.md"
    with open(dest, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out))
    return dest


def main(argv=None):
    argv = argv or sys.argv[1:]
    ws = core.resolve_workspace()
    state = core.load_state(ws)
    session_dir = core.session_dir_from_state(state, ws)
    if argv:
        session_dir = Path(argv[0])
    if session_dir is None:
        print("no active session", file=sys.stderr)
        return 1
    dest = build(session_dir, core.load_config(ws))
    print(dest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
