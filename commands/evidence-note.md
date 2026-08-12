---
description: Annotate an evidence step (label + optional ATT&CK technique)
argument-hint: <seq> "<label>" [--attack Txxxx]
allowed-tools: Bash
---
Annotate an evidence step so it is easy to find later (labels are stored in the mutable `annotations.json`, never in the hash-chained log). Run:

`{{PY}} "{{EVIDENCE_DIR}}/evidence_ctl.py" note $ARGUMENTS`

`$ARGUMENTS` is the step number, a quoted label, and an optional `--attack Txxxx` MITRE technique — pass them through unchanged. Confirm the annotation was recorded and that `map.md` was refreshed.
