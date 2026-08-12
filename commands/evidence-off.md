---
description: Stop evidence capture and seal the manifest
allowed-tools: Bash
---
Stop evidence capture for the current workspace and seal the manifest. Run:

`{{PY}} "{{EVIDENCE_DIR}}/evidence_ctl.py" off`

Report to the user: the manifest path, the final chain hash, the step/screenshot counts, and whether the hash chain verified OK. Capture is now disabled in this workspace — no further tool calls are recorded until `/evidence-on`.
