# Changelog

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions are tagged `v<version>` on GitHub.

To check what's installed vs. what's in your checkout: `python evidence/evidence_ctl.py version` (installed) or `python install.py --check` (compares both, changes nothing).

## [0.2.0] — 2026-08-12

### Fixed
- **Screenshot harvesting silently failed on real installs.** MCP server keys vary per machine — the same tool can be mounted as `windows-mcp`, `windows-deus`, `windows-bighost`, `hexstrike-ai`, `hexstrike_ai`, etc. The old `image_producing_tools` config matched on the full `mcp__<server>__<tool>` name, so it only worked for the exact server keys assumed at build time. Matching is now by short tool name (after the last `__`) by default — portable across any server key. A pattern prefixed with `mcp__` still scopes to one exact server.

### Added
- **Structured MCP responses render as real Markdown tables** in `/evidence-report`, not a JSON dump — auto-detected for any tool returning a list of records (HexStrike scan findings, RedTech query results, WireMCP conversations, ...), including unwrapping the standard MCP content-block envelope. Replaces the old dead `hexstrike_structured_tools` allowlist.
- **Sensitive-data step tagging** — steps from tools that commonly carry secrets (`PowerShell`, `Registry`, `Clipboard`, `browser_network_requests`, `browser_evaluate`, `execute_command`, `execute_python_script`) get a ⚠️ marker in `map.md` and a redaction-reminder callout in the report. Configurable via `sensitive_hint_tools`.
- **Version tracking** — `evidence_ctl.py version`, version shown in `/evidence-status`, and `install.py --check` (dry-run comparison of installed vs. source version, no network call).

## [0.1.0] — 2026-08-12

Initial release.

- `PostToolUse` hook on `Bash` + `mcp__.*` captures every command/tool call as evidence: raw text to `steps/`, real screenshots (filepath or base64 harvest) to `artifacts/`.
- SHA-256 hash chain (`log.jsonl`, append-only) + sealed `manifest.json` on `/evidence-off`.
- Auto-regenerated `map.md` index (screenshots pick-list + full timeline); `annotations.json` for mutable labels/ATT&CK tags outside the chain.
- `/evidence-report` — Markdown report with Pillow+Pygments-rendered command/output PNGs (ANSI-aware) and embedded real screenshots, headed by the manifest hash.
- Installed once globally (`~/.claude/`); evidence stored per-workspace under `<project>/.evidence/`. `install.py` handles install/update/uninstall with idempotent hook merging.
