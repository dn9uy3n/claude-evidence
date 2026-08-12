---
description: Arm evidence auto-capture for an engagement (current workspace)
argument-hint: [engagement-name]
allowed-tools: Bash
---
Arm evidence auto-capture for the CURRENT workspace. Run:

`{{PY}} "{{EVIDENCE_DIR}}/evidence_ctl.py" on $ARGUMENTS`

Then tell the user the engagement name, session id, and store path from the output. From now on every Bash + MCP tool call in this project is recorded as hash-chained evidence under `<workspace>/.evidence/`, until `/evidence-off`. If no engagement name was given, one is auto-generated.
