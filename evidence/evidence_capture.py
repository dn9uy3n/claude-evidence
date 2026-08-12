#!/usr/bin/env python3
"""PostToolUse hook body — capture Bash + MCP calls as chained evidence.

Registered globally for matchers `Bash` and `mcp__.*`. Reads the hook JSON from
stdin, resolves the WORKSPACE (project dir) from the payload cwd, then gates on
that workspace's <workspace>/.evidence/state.json — a fast no-op unless capture
was armed in this project. When armed, under the session lock: reserves a seq,
dumps raw step text, harvests any real screenshot, and appends a hash-chained
record. ALWAYS exits 0 so the agent is never blocked.

Pure standard library on the hot path.
"""

import json
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evidence_core as core  # noqa: E402


# --- text extraction -----------------------------------------------------

_MAX_STR = 8000        # clip individual strings in the JSONL record
_MAX_TEXT = 200000     # clip the full step text file


def _short(tool_name: str) -> str:
    base = tool_name.split("__")[-1] if "__" in tool_name else tool_name
    return "".join(c if (c.isalnum() or c in "._-") else "_" for c in base) or "tool"


def _strip_and_clip(obj, depth=0):
    """Copy `obj` replacing base64 image payloads with a placeholder and
    truncating long strings — keeps the record + raw dump human-readable."""
    if depth > 12:
        return "<max depth>"
    if isinstance(obj, dict):
        out = {}
        is_image = obj.get("type") == "image"
        for k, v in obj.items():
            if is_image and k == "data" and isinstance(v, str):
                out[k] = f"<base64 image, {len(v)} chars stripped>"
            elif k == "source" and isinstance(v, dict) and v.get("data"):
                out[k] = {kk: (f"<base64 image, {len(vv)} chars stripped>"
                               if kk == "data" and isinstance(vv, str) else vv)
                          for kk, vv in v.items()}
            else:
                out[k] = _strip_and_clip(v, depth + 1)
        return out
    if isinstance(obj, list):
        return [_strip_and_clip(v, depth + 1) for v in obj[:200]]
    if isinstance(obj, str) and len(obj) > _MAX_STR:
        return obj[:_MAX_STR] + f"\n...<{len(obj) - _MAX_STR} more chars, see steps/ file>"
    return obj


def _response_to_text(resp) -> str:
    """Flatten an MCP/Bash tool_response into readable text."""
    if resp is None:
        return ""
    if isinstance(resp, str):
        return resp
    if isinstance(resp, list):
        parts = []
        for block in resp:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(str(block.get("text", "")))
                elif block.get("type") == "image":
                    mime = (block.get("mimeType")
                            or (block.get("source") or {}).get("media_type") or "image")
                    parts.append(f"[image content: {mime}]")
                else:
                    parts.append(json.dumps(_strip_and_clip(block), ensure_ascii=False, indent=2))
            else:
                parts.append(str(block))
        return "\n".join(parts)
    if isinstance(resp, dict):
        return json.dumps(_strip_and_clip(resp), ensure_ascii=False, indent=2)
    return str(resp)


def _render_step_text(seq, source, tool_name, tool_input, tool_response, data) -> str:
    lines = [
        f"# EVIDENCE STEP {seq:04d}",
        f"# tool:   {tool_name}  ({source})",
        f"# time:   {core.utc_now_iso()}",
        f"# cwd:    {data.get('cwd', '')}",
        "",
    ]
    if source == "command" and tool_name == "Bash":
        lines.append(f"$ {tool_input.get('command', '')}")
        if tool_input.get("description"):
            lines.append(f"# desc: {tool_input.get('description')}")
        lines.append("")
        lines.append("--- stdout ---")
        lines.append(str((tool_response or {}).get("stdout", "")) if isinstance(tool_response, dict) else "")
        lines.append("")
        lines.append("--- stderr ---")
        lines.append(str((tool_response or {}).get("stderr", "")) if isinstance(tool_response, dict) else "")
    else:
        lines.append("--- tool_input ---")
        lines.append(json.dumps(_strip_and_clip(tool_input), ensure_ascii=False, indent=2))
        lines.append("")
        lines.append("--- tool_response ---")
        lines.append(_response_to_text(tool_response))
    lines.append("")
    lines.append("--- raw tool_response (json, images stripped) ---")
    lines.append(json.dumps(_strip_and_clip(tool_response), ensure_ascii=False, indent=2))
    text = "\n".join(lines)
    return text[:_MAX_TEXT]


def _summarize(source, tool_name, tool_input, tool_response) -> str:
    if source == "command" and tool_name == "Bash" and isinstance(tool_response, dict):
        out = str(tool_response.get("stdout", ""))
        err = str(tool_response.get("stderr", ""))
        interrupted = tool_response.get("interrupted")
        parts = [f"{out.count(chr(10)) + (1 if out else 0)} stdout lines"]
        if err:
            parts.append(f"{err.count(chr(10)) + 1} stderr lines")
        if interrupted:
            parts.append("interrupted")
        return ", ".join(parts)
    text = _response_to_text(tool_response)
    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    return (first[:200] + "…") if len(first) > 200 else first


# --- error sink ----------------------------------------------------------

def _log_error(session_dir, exc, raw):
    try:
        with open(Path(session_dir) / "steps" / "errors.log", "a", encoding="utf-8") as fh:
            fh.write(f"{core.utc_now_iso()} {exc!r}\n{traceback.format_exc()}\n")
    except OSError:
        pass


# --- main ----------------------------------------------------------------

def main() -> int:
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except (ValueError, OSError):
        return 0

    workspace = core.resolve_workspace(data.get("cwd"))
    state = core.load_state(workspace)
    if not state.get("enabled"):
        return 0
    session_dir = core.session_dir_from_state(state, workspace)
    if session_dir is None or not session_dir.exists():
        return 0

    config = core.load_config(workspace)
    cap = state.get("capture") or config.get("capture") or {}

    tool_name = data.get("tool_name", "")
    cmd_mcp = set(config.get("command_producing_mcp_tools", []))

    if tool_name == "Bash":
        if not cap.get("bash", True):
            return 0
        source = "command"
    elif tool_name.startswith("mcp__"):
        if not cap.get("mcp", True):
            return 0
        source = "command" if core.match_tool(tool_name, cmd_mcp) else "mcp"
    else:
        return 0  # only Bash + MCP are evidence sources

    tool_input = data.get("tool_input") or {}
    tool_response = data.get("tool_response")
    tool_short = _short(tool_name)

    try:
        with core.log_lock(session_dir):
            head = core.read_head(session_dir)
            seq = int(head.get("seq", 0)) + 1
            prev = head.get("record_sha256", core.GENESIS_HASH)

            steps_name = f"{seq:04d}-{tool_short}.txt"
            steps_path = session_dir / "steps" / steps_name
            steps_path.parent.mkdir(parents=True, exist_ok=True)
            with open(steps_path, "w", encoding="utf-8") as fh:
                fh.write(_render_step_text(seq, source, tool_name, tool_input, tool_response, data))

            # Structured sidecar for MCP responses — lets the report render a real
            # Markdown table (renderer.to_table) instead of a flat JSON dump, for
            # ANY tool whose response is list-of-dict shaped (not just a hardcoded
            # tool-name allowlist).
            response_json_name = None
            if source == "mcp":
                response_json_name = f"{seq:04d}-{tool_short}.json"
                with open(session_dir / "steps" / response_json_name, "w", encoding="utf-8") as fh:
                    json.dump(_strip_and_clip(tool_response), fh, ensure_ascii=False)

            sensitive_hint = core.match_tool(tool_name, config.get("sensitive_hint_tools", []))

            art = None
            if cap.get("screenshots", True):
                try:
                    import artifact_harvester
                    art = artifact_harvester.harvest(
                        tool_name, tool_input, tool_response, session_dir, seq, tool_short, config)
                except Exception:
                    art = None

            record = {
                "ts": core.utc_now_iso(),
                "session_id": state.get("session_id"),
                "cwd": data.get("cwd"),
                "source": source,
                "tool_name": tool_name,
                "tool_input": _strip_and_clip(tool_input),
                "tool_response_summary": _summarize(source, tool_name, tool_input, tool_response),
                "text_path": f"steps/{steps_name}",
                "response_json_path": f"steps/{response_json_name}" if response_json_name else None,
                "artifact_path": art["artifact_path"] if art else None,
                "artifact_kind": art["artifact_kind"] if art else None,
                "artifact_sha256": art["artifact_sha256"] if art else None,
                "sensitive_hint": sensitive_hint,
                "attack_technique": None,
            }
            core.commit_record(session_dir, record, seq, prev)

        if (config.get("map") or {}).get("regenerate_on_capture", True):
            try:
                import map_builder
                map_builder.build(session_dir, config)
            except Exception:
                pass
    except Exception as exc:
        _log_error(session_dir, exc, raw)

    return 0


if __name__ == "__main__":
    sys.exit(main())
