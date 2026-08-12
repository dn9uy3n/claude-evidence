---
description: Capture a desktop screenshot as evidence (Windows-MCP)
argument-hint: [--display 0] [--note "<label>"]
allowed-tools: Bash
---
Capture desktop evidence: `$ARGUMENTS`

First confirm capture is armed (`{{PY}} "{{EVIDENCE_DIR}}/evidence_ctl.py" status`); if OFF, tell the user to run `/evidence-on` first and stop.

This needs the `windows-mcp` server (`CursorTouch/Windows-MCP`) connected. If `mcp__windows-mcp__Screenshot` is not available, tell the user to add it (`claude mcp add --transport stdio windows-mcp -- uvx windows-mcp serve`) and stop.

Then:
1. Call `mcp__windows-mcp__Screenshot` for the requested `--display` (base64 image). The PostToolUse hook auto-harvests it into `.evidence/.../artifacts/` as a real PNG and chains it. For 2K/4K monitors set `WINDOWS_MCP_SCREENSHOT_SCALE=0.5` to stay under the 1 MB tool-result limit.
2. Run `{{PY}} "{{EVIDENCE_DIR}}/evidence_ctl.py" status` to read the new step number.
3. If a `--note` was given, run `{{PY}} "{{EVIDENCE_DIR}}/evidence_ctl.py" note <seq> "<note>"`.

Report the captured artifact path and step seq to the user.
