# claude-evidence

Automatic evidence capture for **Claude Code**, built for authorized pentest / red-team engagements.

Once armed with a slash command, every `Bash` call and every MCP tool call in the current project is recorded as **tamper-evident evidence** — raw command + output as the source of truth, plus **real pixel screenshots** harvested from image-producing MCPs. It auto-builds a scannable `map.md` index and, on demand, a report-ready Markdown deliverable with a client-verifiable hash.

It is built to sit **underneath your AI security tooling** — the browser agents, desktop drivers, and offensive scanners you already drive through Claude Code — and turn their output into evidence with zero copy-paste. First-class support for [Playwright MCP](https://github.com/microsoft/playwright-mcp), [Windows-MCP](https://github.com/CursorTouch/Windows-MCP), and [HexStrike AI](https://github.com/0x4m4/hexstrike-ai); the generic `mcp__.*` hook captures every other MCP server too. See [Works with your AI tooling](#works-with-your-ai-tooling).

- **Installed once, globally** (`~/.claude/`) → the hook + `/evidence-*` commands work in every project.
- **Evidence stored per-workspace** → each project/session writes to its own `<project>/.evidence/`. The install location never holds evidence.
- **Integrity by SHA-256 hash chain** → any edit, deletion, or reorder of a step breaks the chain and is reported.
- **Pure standard library on the capture path** → arming never fails on a missing dependency. Pillow + Pygments are needed only to render the report.

> The store keeps **raw, unredacted** evidence by design. Redaction is the operator's step before a report leaves your hands. `.evidence/` is auto-added to the project's `.gitignore`.

---

## Install

Requires Python 3.9+.

```bash
git clone https://github.com/dn9uy3n/claude-evidence
cd claude-evidence
python install.py
```

This copies the engine to `~/.claude/evidence/`, writes the 8 `/evidence-*` slash commands to `~/.claude/commands/`, merges a `PostToolUse` hook (matchers `Bash` and `mcp__.*`) into `~/.claude/settings.json`, and pip-installs Pillow + Pygments.

Then **restart Claude Code** so it loads the new hooks and commands.

Options:

```bash
python install.py --dir /path/to/.claude   # install to a non-default Claude dir
python install.py --python /path/to/python # bake a specific interpreter into the hook
python install.py --no-deps                # skip Pillow/Pygments (report rendering off)
python install.py --uninstall              # remove hook + commands + code (keeps evidence)
```

## Update

Re-running the installer **is** the update — it overwrites the installed code + slash commands and re-merges the hook idempotently (no duplicates). Your edited `evidence.config.json` is preserved unless you ask for it back.

```bash
python install.py            # push the current working tree into the install dir (local edits)
python install.py --update   # git pull this repo first, then re-install
python install.py --force-config   # also refresh evidence.config.json (old one saved to .bak)
```

Restart Claude Code after an update so it reloads the hook + commands. Stale `.pyc` files are cleared automatically; per-project `.evidence/` stores are never touched.

## Use

In any project, inside Claude Code:

```
/evidence-on acme-corp-q1-2026        # arm capture for this workspace
   ... do the engagement — Bash + MCP calls are recorded automatically ...
/evidence-snap-web https://target/app --note "IDOR user 4412"
/evidence-note 7 "thick-client after exploit" --attack T1190
/evidence-status                      # armed? counts, chain integrity
/evidence-map                         # (re)generate the map.md index
/evidence-report                      # build the Markdown report
/evidence-off                         # verify chain, seal manifest, stop
```

| Command | What it does |
|---|---|
| `/evidence-on [name]` | Arm capture; create `<project>/.evidence/<name>/<session>/`. |
| `/evidence-off` | Verify the chain, seal `manifest.json`, stop recording. |
| `/evidence-status` | Armed? engagement, step/screenshot counts, chain integrity. |
| `/evidence-note <seq> "<label>" [--attack Txxxx]` | Annotate a step (mutable, outside the chain). |
| `/evidence-map` | Regenerate `map.md` (screenshots pick-list + full timeline). |
| `/evidence-report [--format md]` | Build the Markdown report + rendered PNGs. |
| `/evidence-snap-web <url> [--selector css] [--note ..]` | Drive Playwright to screenshot a page (auto-harvested). |
| `/evidence-snap-desktop [--display 0] [--note ..]` | Drive Windows-MCP to screenshot the desktop (auto-harvested). |

## Works with your AI tooling

The point of this tool is that your offensive work already flows through MCP servers — a headless browser here, a desktop driver there, a farm of scanners somewhere else. This hook sits under all of them: whatever tool you drive, its command, structured result, and any screenshot become evidence automatically. Two harvest modes (`filepath` and `base64`) map exactly onto how these tools return images.

| MCP tool | Repo | What it produces | Captured as |
|---|---|---|---|
| **Playwright MCP** | [microsoft/playwright-mcp](https://github.com/microsoft/playwright-mcp) | browser screenshots (saved file path), DOM snapshots, console/network | real PNG via **filepath** harvest + full response text |
| **Windows-MCP** | [CursorTouch/Windows-MCP](https://github.com/CursorTouch/Windows-MCP) | desktop screenshots (base64), `PowerShell` output, UI actions | real PNG via **base64** harvest; `PowerShell` logged as a command |
| **HexStrike AI** | [0x4m4/hexstrike-ai](https://github.com/0x4m4/hexstrike-ai) | `nmap_scan` / `nuclei_scan` / `sqlmap_scan` / `ffuf_scan` / … structured findings + Browser-Agent screenshots | structured tables in the report + real PNG (`auto` harvest) |
| **any other MCP** | — | RedTech recon graph, WireMCP PCAP, Jadx / ILSpy / Binary Ninja RE, SSH, … | full `tool_input` + `tool_response` text, chained like everything else |

**Connect the tools** (then run `/mcp` to confirm each server's exact prefix, and adjust `image_producing_tools` in the config if a name differs):

```bash
# Playwright MCP — real browser screenshots
claude mcp add playwright -- npx @playwright/mcp@latest
npx playwright install chromium

# Windows-MCP — real desktop screenshots + PowerShell (2K/4K: set WINDOWS_MCP_SCREENSHOT_SCALE=0.5)
claude mcp add --transport stdio windows-mcp -- uvx windows-mcp serve

# HexStrike AI — offensive scanner farm (server process + MCP bridge)
python3 hexstrike-ai/hexstrike_server.py --port 8888
claude mcp add --transport stdio hexstrike-ai -- python3 hexstrike-ai/hexstrike_mcp.py --server http://localhost:8888
```

You capture screenshots either passively (just call the tool — the hook harvests the result) or explicitly with `/evidence-snap-web` (Playwright) and `/evidence-snap-desktop` (Windows-MCP). A failed tool call is evidence too: the record is still written so gaps in an engagement are visible.

## What lands on disk

```
<project>/.evidence/
├── state.json                         # armed? which session (per workspace)
└── <engagement>/
    ├── manifest.json                  # sealed final hash (on /evidence-off)
    └── <session_id>/
        ├── log.jsonl                  # SOURCE OF TRUTH — append-only, hash-chained
        ├── head.json                  # chain head {seq, record_sha256}
        ├── map.md                     # human index (auto-regenerated)
        ├── annotations.json           # your labels (mutable, outside the chain)
        ├── steps/     0001-Bash.txt · 0002-nmap_scan.txt · …
        ├── artifacts/ 0003-browser_take_screenshot.png · …   (real screenshots)
        └── report/    report.md + img/*.png                  (on /evidence-report)
```

## How it works

- A global `PostToolUse` hook runs `evidence_capture.py` after **every** tool call. It resolves the workspace from the call's `cwd`, reads that workspace's `.evidence/state.json`, and is a fast no-op unless capture was armed there.
- When armed, under a cross-platform file lock it reserves a sequence number, dumps the full raw step text to `steps/`, harvests any real screenshot to `artifacts/`, and appends a hash-chained record to `log.jsonl` — `record_sha256 = sha256(prev_sha256 + canonical_json(record))`.
- `map.md` is regenerated after each capture from `log.jsonl` + `annotations.json`.
- `/evidence-report` renders each step's command/output to a PNG (Pillow + Pygments, with an ANSI-color path for scanner output like nmap/sqlmap) and embeds the real screenshots, headed by the manifest / chain hash.

## Configuration

Defaults live in `~/.claude/evidence/evidence.config.json` and are preserved across re-installs. A project may override any top-level key with `<project>/.evidence/evidence.config.json`. Notable keys: `capture` (toggle bash/mcp/screenshots), `map.regenerate_on_capture`, `image_producing_tools` (which MCP tools yield screenshots and how — `filepath` / `base64` / `auto`), `command_producing_mcp_tools` (e.g. Windows-MCP `PowerShell`).

## Notes

- **Not connected yet ≠ unsupported.** `windows-mcp` / `hexstrike-ai` mappings ship pre-wired and inert; the `mcp__.*` matcher captures every MCP regardless, and screenshots harvest the moment those servers are added.
- **Windows / macOS / Linux.** Integrity is the hash chain (portable); on Linux you may additionally `chattr +a log.jsonl`, on Windows use an `icacls` deny-write ACL, for OS-level append-only hardening.
- Not a replacement for git history — file contents at a point in time come from git, not from this log.

## License

MIT — see [LICENSE](LICENSE).
