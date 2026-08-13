# Changelog

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions are tagged `v<version>` on GitHub.

To check what's installed vs. what's in your checkout: `python evidence/evidence_ctl.py version` (installed) or `python install.py --check` (compares both, changes nothing).

## [0.4.4] — 2026-08-13

### Fixed
- **A step could be silently dropped with `UnicodeEncodeError`.** Captured tool text occasionally contains a lone (unpaired) Unicode surrogate — typically from a subprocess whose output got decoded with the wrong codepage upstream (seen on Windows). UTF-8 cannot encode that codepoint at all, so the very first disk write for the step raised, the step never made it into `log.jsonl`, and the only trace was an entry in `steps/errors.log`. Tool payloads are now sanitized (bad codepoints replaced with a visible `\udXXX`-style marker) immediately after the hook parses them — once, at the top — so the hash, the JSON sidecar, and the on-disk text all stay consistent; patching only the final write call risks the hash and the on-disk bytes silently diverging, which `verify_chain` would then misreport as tampering.

## [0.4.3] — 2026-08-13

### Fixed
- **One verbose JSON field could push the actually-important fields out of the image entirely.** A response with a long string value (e.g. a multi-KB SQL debug string in a "query" field) would wrap into dozens of rows on its own, consuming the whole `max_lines` budget before later fields (`status`, `rowcount`, the actual result data) ever got drawn — silently dropped, with only the generic "truncated" notice at the bottom as a clue. Long string *values* inside embedded JSON are now clipped (with a `… <N more chars, see steps/ file>` marker) before pretty-printing, so no single field can starve the rest of the structure out of the rendered image. Unclipped, full-fidelity data is unaffected in `steps/*.txt` and the JSON sidecar.

## [0.4.2] — 2026-08-13

### Changed
- **Embedded JSON now pretty-prints before wrapping.** 0.4.1 fixed long lines being silently cut, by wrapping them — but a long `curl -d '{...}'` payload or raw JSON API response wrapped at a fixed character column still buried the field you actually care about mid-line. Any line containing a parseable JSON object/array (a `-d` payload, a raw response body) is now pretty-printed one field per line before rendering, so a specific value is easy to spot instead of hidden in a wall of wrapped text. Non-JSON lines and ANSI-colored output are untouched.

## [0.4.1] — 2026-08-13

### Fixed
- **Rendered step PNGs silently dropped content on long lines.** `render_text()` hard-truncated any line past 140 characters with a bare `…`, no notice — a long `curl -d '{...}'` JSON payload or a long JSON API response (very common evidence) would visibly lose data in the image itself, with no indication anything was cut. Long lines now wrap onto additional rows in the image instead of being cut; nothing is dropped. The existing `max_lines` cap (with its truncation notice) still applies if the *wrapped* image would otherwise get very tall.

## [0.4.0] — 2026-08-13

### Added
- **`/evidence-resume` / `evidence_ctl.py resume`** — re-arm a previously stopped session so new Bash + MCP calls keep appending to its same hash-chained `log.jsonl`, instead of always starting a fresh session on `/evidence-on`. `resume --list` shows every session recorded in the workspace, across all engagements. Refuses to resume if the session's chain is broken.
- **Real screenshots take priority in the report.** A step that already has a harvested screenshot (Playwright, Windows-MCP, ...) now shows that image directly — the report no longer also renders a redundant PNG-of-text for it.

### Changed
- **Step sequence numbers are now 8 digits** (`00000001` instead of `0001`), everywhere a seq appears — `steps/`, `artifacts/`, `map.md`, the report. Headroom for long engagements; old 4-digit filenames from prior sessions still work (only new sessions use the wider format, nothing renames existing files).

## [0.3.3] — 2026-08-13

### Fixed
- **Multi-line commands got truncated to their first line in the rendered PNG.** The 0.3.2 cleanup split the header on the first `\n`, assuming a command was always one line — real commands with line-continuations (`\`) or multiple statements span several lines, and everything past the first line (including a following `echo`, second pipeline stage, etc.) was silently dropped from the image. Now splits on the fixed `\n\n--- stdout ---` separator instead, so the full command — however many lines — survives intact; the `# desc:` line (if present) is still stripped correctly regardless of how long the command block is.

## [0.3.2] — 2026-08-13

### Fixed
- **Rendered step PNGs still showed the `# desc:` line and the `--- stdout ---`/`--- stderr ---`/`--- tool_input ---`/`--- tool_response ---` labels.** These are internal recording labels, not something a real terminal session would show, and (for `tool_input`) redundant with the fenced JSON block the report already prints just above the image. The PNG for a Bash step is now literally `$ command` followed by its real stdout/stderr, nothing else; for an MCP step it's just the response content, since the input is already shown separately. Same scope as before: only the rendered PNG changed, `steps/*.txt` still records everything, labels included.

## [0.3.1] — 2026-08-13

### Fixed
- **Rendered step PNGs repeated metadata already shown in the report.** `render_step()` re-rendered the full `# EVIDENCE STEP .../tool/time/cwd` preamble from `steps/*.txt` into the image, duplicating the seq/tool/timestamp already printed as the step heading, timestamp, and image caption around it. The PNG now starts straight at `$ command` (or `--- tool_input ---` for MCP steps) — a clean transcript instead of a metadata dump. The raw `steps/*.txt` file is untouched (still the full, unredacted record).
- **Rendered step PNGs showed empty `--- stdout ---`/`--- stderr ---` sections with nothing under them.** A Bash step with no stderr (the common case) still got a bare `--- stderr ---` label taking up space in the image. Empty sections are now dropped from the rendered PNG; a section with real content is left as-is. Raw `steps/*.txt` still always records both labels, even when empty — nothing is hidden from the source-of-truth file.
- Regenerating an existing session's report (`/evidence-report` again after updating) picks up both fixes automatically — nothing needs to be re-armed or re-captured, since the report is always rebuilt fresh from `log.jsonl`/`steps/*.txt`.

## [0.3.0] — 2026-08-12

### Changed
- **Capture is now scoped to Bash + declared AI tools by default** — Playwright, Windows-MCP, and HexStrike AI (matched by server key, portable across `windows-mcp`/`windows-deus`/`windows-bighost` and `hexstrike-ai`/`hexstrike_ai` naming). Calls to any other connected MCP server (RedTech, WireMCP, Jadx, ILSpy, Binary Ninja, SSH, ...) are no longer captured — this was previously "any other MCP" as a supported, documented path; now it's out of scope by default. New config key `allowed_mcp_servers` (glob patterns against the server key); leave it empty/absent to restore capturing every connected MCP server. `/evidence-status` shows the active scope.

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
