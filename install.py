#!/usr/bin/env python3
"""Installer for the Claude Code evidence auto-capture tool.

Installs the tool ONCE into a Claude config dir (default: ~/.claude) so the
capture hook + /evidence-* slash commands are available in EVERY project. The
evidence itself is always written per-workspace, under <project>/.evidence/ — the
install location only holds the code + default config, never evidence.

  python install.py                 # install (or re-install/update) to ~/.claude
  python install.py --update        # git pull the repo, then re-install code/commands/hooks
  python install.py --dir DIR       # install to a different Claude config dir
  python install.py --python PATH   # bake a specific interpreter into hooks
  python install.py --force-config  # also overwrite evidence.config.json (backs up the old)
  python install.py --no-deps       # skip pip install of Pillow/Pygments
  python install.py --uninstall     # remove hooks, commands, and evidence code

Re-running the installer IS the update path: it overwrites the installed code +
commands and re-merges the hook idempotently (no duplicates). Your edited
evidence.config.json is preserved unless you pass --force-config. Use --update to
`git pull` this repo first (when you track upstream); a plain re-run just pushes
the current working tree into the install dir (handy while developing locally).
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent
SRC_EVIDENCE = SRC / "evidence"
SRC_COMMANDS = SRC / "commands"

HOOK_SCRIPT = "evidence_capture.py"
COMMAND_GLOB = "evidence-*.md"


def _q(path) -> str:
    return f'"{path}"'


def _clear_pycache(directory: Path) -> None:
    pc = directory / "__pycache__"
    if pc.exists():
        shutil.rmtree(pc, ignore_errors=True)


def _git_pull(repo: Path) -> None:
    if not (repo / ".git").exists():
        print("--update: not a git checkout, skipping pull (using current files)")
        return
    try:
        r = subprocess.run(["git", "-C", str(repo), "pull", "--ff-only"],
                           capture_output=True, text=True)
        msg = (r.stdout + r.stderr).strip().splitlines()
        print(f"git pull: {msg[-1] if msg else 'done'}")
    except OSError as exc:
        print(f"git pull skipped ({exc}) -- installing current files")


def _is_evidence_group(group: dict) -> bool:
    for h in group.get("hooks", []):
        if HOOK_SCRIPT in str(h.get("command", "")):
            return True
    return False


def _merge_hooks(settings: dict, py: str, evidence_dir: Path) -> dict:
    cmd = f'{_q(py)} {_q(str(evidence_dir / HOOK_SCRIPT))}'
    hooks = settings.setdefault("hooks", {})
    post = hooks.setdefault("PostToolUse", [])
    # drop any prior evidence hook groups so re-install doesn't duplicate
    post = [g for g in post if not _is_evidence_group(g)]
    for matcher in ("Bash", "mcp__.*"):
        post.append({"matcher": matcher, "hooks": [{"type": "command", "command": cmd}]})
    hooks["PostToolUse"] = post
    return settings


def _strip_hooks(settings: dict) -> dict:
    post = settings.get("hooks", {}).get("PostToolUse", [])
    settings["hooks"]["PostToolUse"] = [g for g in post if not _is_evidence_group(g)]
    return settings


def install(claude_dir: Path, py: str, deps: bool, force_config: bool = False) -> None:
    evidence_dir = claude_dir / "evidence"
    commands_dir = claude_dir / "commands"
    settings_path = claude_dir / "settings.json"
    updating = evidence_dir.exists()
    evidence_dir.mkdir(parents=True, exist_ok=True)
    commands_dir.mkdir(parents=True, exist_ok=True)

    # 1. copy code (always overwrite); preserve a user-edited config unless forced
    for f in SRC_EVIDENCE.iterdir():
        if f.suffix == ".py" or f.name == "requirements.txt":
            shutil.copy2(f, evidence_dir / f.name)
    _clear_pycache(evidence_dir)  # drop stale .pyc after a code update
    cfg_dst = evidence_dir / "evidence.config.json"
    if not cfg_dst.exists():
        shutil.copy2(SRC_EVIDENCE / "evidence.config.json", cfg_dst)
        cfg_note = "installed default config"
    elif force_config:
        backup = cfg_dst.with_suffix(".json.bak")
        shutil.copy2(cfg_dst, backup)
        shutil.copy2(SRC_EVIDENCE / "evidence.config.json", cfg_dst)
        cfg_note = f"refreshed config (old -> {backup.name})"
    else:
        cfg_note = "kept existing config (use --force-config to refresh)"

    # 2. template + copy slash commands
    ev_posix = evidence_dir.as_posix()
    n_cmd = 0
    for tmpl in sorted(SRC_COMMANDS.glob(COMMAND_GLOB)):
        body = tmpl.read_text(encoding="utf-8")
        body = body.replace("{{PY}}", _q(py)).replace("{{EVIDENCE_DIR}}", ev_posix)
        (commands_dir / tmpl.name).write_text(body, encoding="utf-8")
        n_cmd += 1

    # 3. merge hooks into settings.json (preserve everything else)
    settings = {}
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            backup = settings_path.with_suffix(".json.bak")
            shutil.copy2(settings_path, backup)
            print(f"  ! existing settings.json was invalid JSON — backed up to {backup}")
            settings = {}
    _merge_hooks(settings, py, evidence_dir)
    settings_path.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # 4. dependencies (rendering only; capture is stdlib)
    dep_note = "skipped (--no-deps)"
    if deps:
        req = evidence_dir / "requirements.txt"
        try:
            subprocess.run([py, "-m", "pip", "install", "-q", "-r", str(req)], check=True)
            dep_note = "installed Pillow + Pygments"
        except (subprocess.CalledProcessError, OSError) as exc:
            dep_note = f"FAILED ({exc}) — capture still works; run pip install -r {req} for report rendering"

    print(f"Evidence tool {'updated' if updating else 'installed'}.")
    print(f"  claude dir: {claude_dir}")
    print(f"  code:       {evidence_dir}  ({cfg_note})")
    print(f"  commands:   {commands_dir}  ({n_cmd} slash commands)")
    print(f"  hooks:      {settings_path}  (PostToolUse: Bash + mcp__.*)")
    print(f"  python:     {py}")
    print(f"  deps:       {dep_note}")
    print()
    print("Restart Claude Code so it loads the new hooks + commands, then in any project:")
    print("  /evidence-on <engagement>  ->  work  ->  /evidence-report  ->  /evidence-off")
    print("Evidence is written under <that project>/.evidence/ -- never in the install dir.")


def uninstall(claude_dir: Path) -> None:
    evidence_dir = claude_dir / "evidence"
    commands_dir = claude_dir / "commands"
    settings_path = claude_dir / "settings.json"

    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
            _strip_hooks(settings)
            settings_path.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except json.JSONDecodeError:
            print("  ! settings.json invalid — left untouched")
    for cmd in commands_dir.glob(COMMAND_GLOB):
        cmd.unlink()
    if evidence_dir.exists():
        shutil.rmtree(evidence_dir, ignore_errors=True)
    print(f"Evidence tool removed from {claude_dir}. Per-project .evidence/ stores were left intact.")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Install the Claude Code evidence auto-capture tool")
    ap.add_argument("--dir", default=str(Path.home() / ".claude"), help="Claude config dir (default: ~/.claude)")
    ap.add_argument("--python", default=sys.executable, help="Interpreter baked into hooks/commands (default: this Python)")
    ap.add_argument("--update", action="store_true", help="git pull this repo, then re-install")
    ap.add_argument("--no-pull", action="store_true", help="With --update, skip the git pull")
    ap.add_argument("--force-config", action="store_true", help="Overwrite evidence.config.json (backs up the old one)")
    ap.add_argument("--no-deps", action="store_true", help="Skip pip install of Pillow/Pygments")
    ap.add_argument("--uninstall", action="store_true", help="Remove the tool")
    args = ap.parse_args(argv)

    claude_dir = Path(args.dir).expanduser()
    if args.uninstall:
        uninstall(claude_dir)
    else:
        if args.update and not args.no_pull:
            _git_pull(SRC)
        install(claude_dir, args.python, deps=not args.no_deps, force_config=args.force_config)
    return 0


if __name__ == "__main__":
    sys.exit(main())
