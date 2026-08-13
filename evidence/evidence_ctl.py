#!/usr/bin/env python3
"""Control CLI for the evidence auto-capture tool.

Deterministic file operations only (no MCP). Driven by the /evidence-* slash
commands via the Bash tool. Operates on the CURRENT WORKSPACE — evidence and
state live under <workspace>/.evidence/, so each project/session is independent
even though the tool itself is installed once (globally).

  on [engagement]        arm capture; create <ws>/.evidence/<engagement>/<session>/
  off                    verify chain, seal manifest.json, stop capturing
  resume [session]       re-arm a previously stopped session (same chain, no new session)
  status                 enabled? engagement, counts, chain integrity, version
  note <seq> "<label>"   annotate a step (optionally --attack Txxxx)
  map                    regenerate map.md
  report [--format md]   build the Markdown report
  version                print the installed tool version (see CHANGELOG.md)
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evidence_core as core  # noqa: E402
import map_builder  # noqa: E402

WORKSPACE = core.resolve_workspace()


def _sanitize(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-") or "engagement"


def _regen_map(session_dir):
    try:
        map_builder.build(session_dir, core.load_config(WORKSPACE))
    except Exception as exc:  # non-fatal
        print(f"(map regen skipped: {exc})", file=sys.stderr)


def _ensure_gitignore():
    gi = WORKSPACE / ".gitignore"
    line = ".evidence/"
    existing = gi.read_text(encoding="utf-8") if gi.exists() else ""
    if line not in existing.splitlines():
        with open(gi, "a", encoding="utf-8") as fh:
            fh.write(("" if not existing or existing.endswith("\n") else "\n") + line + "\n")


def _list_sessions(config):
    """Every session dir this workspace has ever recorded (has a log.jsonl),
    across all engagements — not just the one state.json currently tracks.
    Most recent first (session ids sort chronologically as strings)."""
    root = WORKSPACE / config.get("output_root", ".evidence")
    if not root.exists():
        return []
    out = []
    for eng_dir in root.iterdir():
        if not eng_dir.is_dir():
            continue
        for sess_dir in eng_dir.iterdir():
            if sess_dir.is_dir() and (sess_dir / "log.jsonl").exists():
                out.append((eng_dir.name, sess_dir.name, sess_dir))
    out.sort(key=lambda t: t[1], reverse=True)
    return out


# --- verbs ---------------------------------------------------------------

def cmd_on(args) -> int:
    config = core.load_config(WORKSPACE)
    state = core.load_state(WORKSPACE)
    if state.get("enabled"):
        print(f"Already armed in this workspace: {state.get('engagement')} / {state.get('session_id')}")
        return 0

    engagement = _sanitize(args.engagement or "engagement")
    session_id = core.new_session_id()
    root = config.get("output_root", ".evidence")
    output_dir = f"{root}/{engagement}/{session_id}"
    session_dir = WORKSPACE / output_dir
    core.ensure_session_dirs(session_dir)
    core.write_json(session_dir / "annotations.json", {})

    core.save_state({
        "enabled": True,
        "engagement": engagement,
        "session_id": session_id,
        "started_at": core.utc_now_iso(),
        "output_dir": output_dir,
        "capture": config.get("capture", {"bash": True, "mcp": True, "screenshots": True}),
    }, WORKSPACE)
    _ensure_gitignore()
    _regen_map(session_dir)
    print(f"Evidence capture ARMED (workspace: {WORKSPACE}).")
    print(f"  engagement: {engagement}")
    print(f"  session:    {session_id}")
    print(f"  store:      {output_dir}")
    return 0


def cmd_off(args) -> int:
    state = core.load_state(WORKSPACE)
    if not state.get("enabled"):
        print("Evidence capture already OFF in this workspace.")
        return 0
    session_dir = core.session_dir_from_state(state, WORKSPACE)
    chain = core.verify_chain(session_dir)
    head = core.read_head(session_dir)
    records = list(core.iter_records(session_dir))
    shots = sum(1 for r in records if r.get("artifact_path"))

    manifest = {
        "engagement": state.get("engagement"),
        "session_id": state.get("session_id"),
        "started_at": state.get("started_at"),
        "ended_at": core.utc_now_iso(),
        "steps": len(records),
        "screenshots": shots,
        "final_record_sha256": head.get("record_sha256", core.GENESIS_HASH),
        "chain_ok": chain["ok"],
        "chain_break_at": chain["break_at"],
        "integrity": "sha256-hash-chain",
    }
    core.write_json(session_dir.parent / "manifest.json", manifest)
    _regen_map(session_dir)

    state["enabled"] = False
    core.save_state(state, WORKSPACE)

    print(f"Evidence capture OFF. Manifest sealed: {session_dir.parent / 'manifest.json'}")
    print(f"  steps: {len(records)}  screenshots: {shots}  chain: {'OK' if chain['ok'] else 'BROKEN @ ' + str(chain['break_at'])}")
    print(f"  final hash: {manifest['final_record_sha256']}")
    return 0


def cmd_resume(args) -> int:
    config = core.load_config(WORKSPACE)
    state = core.load_state(WORKSPACE)

    if args.list:
        sessions = _list_sessions(config)
        if not sessions:
            print("No sessions found in this workspace.")
            return 0
        cur_eng, cur_sess, cur_on = state.get("engagement"), state.get("session_id"), state.get("enabled")
        for eng, sess, sdir in sessions:
            n = sum(1 for _ in core.iter_records(sdir))
            tag = " (current, armed)" if cur_on and eng == cur_eng and sess == cur_sess else ""
            print(f"  {eng}/{sess}  ({n} steps){tag}")
        print("\nResume with: evidence_ctl.py resume <session-id> [--engagement <name>]")
        return 0

    if state.get("enabled"):
        print(f"Already armed: {state.get('engagement')} / {state.get('session_id')} -- nothing to resume.")
        return 0

    root = WORKSPACE / config.get("output_root", ".evidence")
    if args.session:
        if "/" in args.session:
            engagement, session_id = args.session.split("/", 1)
        else:
            session_id, engagement = args.session, args.engagement
        if engagement:
            session_dir = root / engagement / session_id
        else:
            matches = [(e, s, d) for e, s, d in _list_sessions(config) if s == session_id]
            if not matches:
                print(f"No session '{session_id}' found. Run `resume --list` to see what's available.", file=sys.stderr)
                return 1
            if len(matches) > 1:
                print(f"Multiple sessions match '{session_id}':", file=sys.stderr)
                for e, s, _d in matches:
                    print(f"  {e}/{s}", file=sys.stderr)
                print("Disambiguate with --engagement.", file=sys.stderr)
                return 1
            engagement, session_id, session_dir = matches[0]
    else:
        engagement, session_id = state.get("engagement"), state.get("session_id")
        if not session_id:
            print("No prior session in this workspace to resume. Try `resume --list` or `/evidence-on`.", file=sys.stderr)
            return 1
        session_dir = root / engagement / session_id

    if not (session_dir / "log.jsonl").exists():
        print(f"Session not found: {session_dir}", file=sys.stderr)
        return 1

    chain = core.verify_chain(session_dir)
    if not chain["ok"]:
        print(f"Refusing to resume -- chain BROKEN @ #{chain['break_at']} ({chain['reason']}). "
              "This session's evidence has been altered since it was written.", file=sys.stderr)
        return 1

    records = list(core.iter_records(session_dir))
    started_at = records[0]["ts"] if records else core.utc_now_iso()
    output_dir = str(session_dir.relative_to(WORKSPACE)).replace("\\", "/")

    core.save_state({
        "enabled": True,
        "engagement": engagement,
        "session_id": session_id,
        "started_at": started_at,
        "output_dir": output_dir,
        "capture": config.get("capture", {"bash": True, "mcp": True, "screenshots": True}),
    }, WORKSPACE)
    _ensure_gitignore()
    _regen_map(session_dir)

    print(f"Evidence capture RESUMED (workspace: {WORKSPACE}).")
    print(f"  engagement: {engagement}")
    print(f"  session:    {session_id}")
    print(f"  steps so far: {len(records)}  chain: OK")
    if (session_dir.parent / "manifest.json").exists():
        print("  note: this session was previously sealed -- manifest.json will be refreshed on the next /evidence-off")
    return 0


def cmd_version(args) -> int:
    print(core.TOOL_VERSION)
    return 0


def cmd_status(args) -> int:
    state = core.load_state(WORKSPACE)
    config = core.load_config(WORKSPACE)
    allowed = config.get("allowed_mcp_servers") or []
    print(f"version:    {core.TOOL_VERSION}")
    print(f"workspace:  {WORKSPACE}")
    print(f"mcp scope:  {', '.join(allowed) if allowed else 'all connected MCP servers'}")
    print(f"enabled:    {state.get('enabled', False)}")
    print(f"engagement: {state.get('engagement')}")
    print(f"session:    {state.get('session_id')}")
    print(f"started_at: {state.get('started_at')}")
    session_dir = core.session_dir_from_state(state, WORKSPACE)
    if session_dir and session_dir.exists():
        records = list(core.iter_records(session_dir))
        shots = sum(1 for r in records if r.get("artifact_path"))
        chain = core.verify_chain(session_dir)
        print(f"store:      {state.get('output_dir')}")
        print(f"steps:      {len(records)}")
        print(f"screenshots:{shots}")
        print(f"chain:      {'OK' if chain['ok'] else 'BROKEN @ ' + str(chain['break_at']) + ' (' + str(chain['reason']) + ')'}")
    else:
        print("store:      (none)")
    return 0


def cmd_note(args) -> int:
    state = core.load_state(WORKSPACE)
    session_dir = core.session_dir_from_state(state, WORKSPACE)
    if session_dir is None or not session_dir.exists():
        print("No active session in this workspace.", file=sys.stderr)
        return 1
    ann_path = session_dir / "annotations.json"
    annotations = core.load_json(ann_path, default={}) or {}
    if args.attack:
        annotations[str(args.seq)] = {"note": args.label, "attack": args.attack}
    else:
        annotations[str(args.seq)] = args.label
    core.write_json(ann_path, annotations)
    _regen_map(session_dir)
    print(f"Noted step {args.seq}: {args.label}" + (f"  [ATT&CK {args.attack}]" if args.attack else ""))
    return 0


def cmd_map(args) -> int:
    state = core.load_state(WORKSPACE)
    session_dir = core.session_dir_from_state(state, WORKSPACE)
    if session_dir is None or not session_dir.exists():
        print("No active session in this workspace.", file=sys.stderr)
        return 1
    dest = map_builder.build(session_dir, core.load_config(WORKSPACE))
    print(f"map: {dest}")
    return 0


def cmd_report(args) -> int:
    state = core.load_state(WORKSPACE)
    session_dir = core.session_dir_from_state(state, WORKSPACE)
    if session_dir is None or not session_dir.exists():
        print("No active session in this workspace.", file=sys.stderr)
        return 1
    import report_assembler
    if not report_assembler._RENDER:
        print("(note: Pillow/Pygments not installed — using text fallback, no rendered PNGs)", file=sys.stderr)
    dest = report_assembler.build(session_dir, core.load_config(WORKSPACE), fmt=args.format)
    print(f"report: {dest}")
    return 0


def build_parser():
    p = argparse.ArgumentParser(prog="evidence_ctl")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("on"); s.add_argument("engagement", nargs="?"); s.set_defaults(func=cmd_on)
    sub.add_parser("off").set_defaults(func=cmd_off)
    sub.add_parser("status").set_defaults(func=cmd_status)

    s = sub.add_parser("resume")
    s.add_argument("session", nargs="?",
                   help="session id, or <engagement>/<session id>; omit to resume this workspace's last session")
    s.add_argument("--engagement", default=None, help="disambiguate when the session id exists under more than one engagement")
    s.add_argument("--list", action="store_true", help="list resumable sessions instead of resuming one")
    s.set_defaults(func=cmd_resume)

    s = sub.add_parser("note")
    s.add_argument("seq", type=int)
    s.add_argument("label")
    s.add_argument("--attack", default=None)
    s.set_defaults(func=cmd_note)

    sub.add_parser("map").set_defaults(func=cmd_map)

    s = sub.add_parser("report")
    s.add_argument("--format", default="md", choices=["md"])
    s.set_defaults(func=cmd_report)

    sub.add_parser("version").set_defaults(func=cmd_version)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
