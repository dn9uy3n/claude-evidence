---
description: Build the Markdown evidence report
argument-hint: [--format md]
allowed-tools: Bash
---
Build the report-ready Markdown deliverable (timeline, rendered command PNGs, embedded real screenshots, notes, ATT&CK, and the manifest hash header). Run:

`{{PY}} "{{EVIDENCE_DIR}}/evidence_ctl.py" report $ARGUMENTS`

Rendering needs Pillow + Pygments (installed by `install.py`); without them the report still builds with text code-fence fallbacks. Give the user the report path and mention screenshots are pulled from `artifacts/`.
