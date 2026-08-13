---
description: Resume evidence capture on a previously stopped session
argument-hint: [session-id] [--engagement name] [--list]
allowed-tools: Bash
---
Resume evidence capture for the current workspace — re-arm a session that was stopped (via `/evidence-off` or otherwise) so new Bash + MCP calls keep appending to its SAME hash-chained log, instead of starting a fresh session. Run:

`{{PY}} "{{EVIDENCE_DIR}}/evidence_ctl.py" resume $ARGUMENTS`

If `$ARGUMENTS` is empty, this resumes the workspace's last-tracked session. To resume a different one, first run `/evidence-resume --list` to see what's available in this project's `.evidence/`, then `/evidence-resume <session-id>` (add `--engagement <name>` only if that session id exists under more than one engagement). Refuses to resume if the session's hash chain is broken — report that to the user verbatim if it happens. On success, report the engagement, session id, and how many steps are already in it.
