---
description: Regenerate the evidence map (map.md) index
allowed-tools: Bash
---
Regenerate the evidence index `map.md` from `log.jsonl` + `annotations.json`. Run:

`{{PY}} "{{EVIDENCE_DIR}}/evidence_ctl.py" map`

Give the user the path to `map.md`. It has two sections: **📷 Ảnh chụp** (screenshots only — the pick-list for the report) and **🧭 Toàn bộ timeline** (every step). Paths in it are clickable in a Markdown viewer.
