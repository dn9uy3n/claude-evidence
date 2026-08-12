---
description: Capture a browser screenshot as evidence (Playwright MCP)
argument-hint: <url> [--selector <css>] [--note "<label>"]
allowed-tools: mcp__playwright__browser_navigate, mcp__playwright__browser_take_screenshot, Bash
---
Capture web evidence for: `$ARGUMENTS`

First confirm capture is armed (`{{PY}} "{{EVIDENCE_DIR}}/evidence_ctl.py" status`); if it is OFF, tell the user to run `/evidence-on` first and stop.

Then:
1. Parse the URL and optional `--selector` / `--note` from the arguments.
2. `mcp__playwright__browser_navigate` to the URL.
3. `mcp__playwright__browser_take_screenshot` — full page unless a `--selector` was given, in which case screenshot that element. It returns a saved file path; the PostToolUse hook auto-harvests it into `.evidence/.../artifacts/` as a real PNG and chains it.
4. Run `{{PY}} "{{EVIDENCE_DIR}}/evidence_ctl.py" status` to read back the new step number.
5. If a `--note` was given, run `{{PY}} "{{EVIDENCE_DIR}}/evidence_ctl.py" note <seq> "<note>"`.

Report the captured artifact path and step seq to the user.
