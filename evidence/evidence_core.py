"""Shared foundation for the evidence auto-capture tool.

Pure standard library so the capture hot-path never fails on a missing dependency.

The tool is installed ONCE (globally, e.g. ~/.claude/evidence/) but its evidence
store + runtime state live PER WORKSPACE — the project directory where a Claude
Code session is running. So paths split into two roots:

  * TOOL_DIR    -- where these scripts + the default config live (install location)
  * workspace   -- the current project dir; holds <workspace>/.evidence/

Provides: path resolution, config/state IO, canonical hashing, a cross-platform
file lock, hash-chained append, and chain verification.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from fnmatch import fnmatch
from datetime import datetime, timezone
from pathlib import Path

# --- Install location (where the tool's own files live) ------------------

# Bump on every release; install.py reads this (by regex, no import) to compare
# an already-installed copy against the source checkout before overwriting, and
# `evidence_ctl.py version` / `/evidence-status` surface it to the user. See
# CHANGELOG.md for what changed at each version; releases are tagged v<version>.
TOOL_VERSION = "0.4.4"

TOOL_DIR = Path(__file__).resolve().parent
CONFIG_PATH = TOOL_DIR / "evidence.config.json"

GENESIS_HASH = "0" * 64
EVIDENCE_SUBDIR = ".evidence"


# --- Workspace resolution (where evidence is stored, per session) --------

def resolve_workspace(explicit=None) -> Path:
    """The project directory for this session. Preference order:
    explicit (hook payload cwd) -> $CLAUDE_PROJECT_DIR -> current working dir.
    """
    if explicit:
        return Path(explicit)
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return Path(env)
    return Path.cwd()


def evidence_dir(workspace: Path) -> Path:
    return Path(workspace) / EVIDENCE_SUBDIR


def state_path(workspace: Path) -> Path:
    return evidence_dir(workspace) / "state.json"


# --- Time / ids ----------------------------------------------------------

def utc_now_iso() -> str:
    """UTC timestamp, millisecond precision, trailing Z (e.g. 2026-08-12T09:15:10.220Z)."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def new_session_id() -> str:
    """YYYYMMDD-HHMMSS-<4 hex> — unique per engagement session."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{os.urandom(2).hex()}"


# --- Generic JSON IO -----------------------------------------------------

def load_json(path: Path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(path: Path, obj) -> None:
    """Atomic-ish write via temp file + replace."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# --- Config / state ------------------------------------------------------

def _merge(base: dict, over: dict) -> dict:
    """One-level-deep merge (nested dicts merged, everything else replaced)."""
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = {**out[k], **v}
        else:
            out[k] = v
    return out


def load_config(workspace: Path = None) -> dict:
    """Global default config, optionally overridden by
    <workspace>/.evidence/evidence.config.json."""
    cfg = load_json(CONFIG_PATH, default={}) or {}
    if workspace:
        override = load_json(evidence_dir(workspace) / "evidence.config.json", default=None)
        if isinstance(override, dict):
            cfg = _merge(cfg, override)
    return cfg


def load_state(workspace: Path) -> dict:
    return load_json(state_path(workspace), default={"enabled": False}) or {"enabled": False}


def save_state(state: dict, workspace: Path) -> None:
    write_json(state_path(workspace), state)


# --- Tool name matching ---------------------------------------------------
#
# MCP server keys vary per install — the same underlying tool (Windows-MCP,
# HexStrike AI, ...) can be mounted as `windows-mcp`, `windows-deus`,
# `windows-bighost`, `hexstrike-ai`, `hexstrike_ai`, etc. Matching on the full
# `mcp__<server>__<tool>` name is therefore fragile. Config patterns match on
# the SHORT tool name (after the last `__`) by default — portable across any
# server key — unless a pattern is explicitly scoped with an `mcp__` prefix.

def tool_short_name(tool_name: str) -> str:
    return tool_name.split("__")[-1] if "__" in tool_name else tool_name


def match_tool(tool_name: str, patterns) -> bool:
    """True if `tool_name` matches any pattern in `patterns`.

    A pattern starting with 'mcp__' matches the FULL tool name (scopes to one
    server). Any other pattern matches the SHORT name. Glob wildcards (* ?)
    are supported in either form.
    """
    short = tool_short_name(tool_name)
    for pat in patterns or []:
        target = tool_name if pat.startswith("mcp__") else short
        if pat == target or fnmatch(target, pat):
            return True
    return False


def match_tool_value(tool_name: str, mapping: dict):
    """Like `match_tool` but for a {pattern: value} dict — returns the value of
    the most specific match, or None. Precedence: exact full name > full-name
    glob > exact short name > short-name glob.
    """
    if not mapping:
        return None
    short = tool_short_name(tool_name)
    if tool_name in mapping:
        return mapping[tool_name]
    for pat, val in mapping.items():
        if pat.startswith("mcp__") and ("*" in pat or "?" in pat) and fnmatch(tool_name, pat):
            return val
    if short in mapping:
        return mapping[short]
    for pat, val in mapping.items():
        if not pat.startswith("mcp__") and ("*" in pat or "?" in pat) and fnmatch(short, pat):
            return val
    return None


def mcp_server_key(tool_name: str) -> str:
    """The server key from `mcp__<server>__<tool>` — '' if not an MCP tool name."""
    if not tool_name.startswith("mcp__"):
        return ""
    parts = tool_name.split("__")
    return parts[1] if len(parts) > 1 else ""


def server_allowed(tool_name: str, patterns) -> bool:
    """Gate which MCP servers produce evidence at all (separate from `match_tool`,
    which gates behavior WITHIN an already-allowed tool). Non-MCP tool names
    (e.g. Bash) always pass — this only restricts MCP capture. An empty/missing
    `patterns` means no restriction (capture every connected MCP server); a
    non-empty list is a strict allowlist matched against the server key,
    case-insensitive, glob-capable (e.g. "windows-*" covers windows-mcp/
    windows-deus/windows-bighost; "hexstrike*" covers hexstrike-ai/hexstrike_ai).
    """
    if not tool_name.startswith("mcp__"):
        return True
    if not patterns:
        return True
    server = mcp_server_key(tool_name).lower()
    return any(fnmatch(server, str(pat).lower()) for pat in patterns)


# --- Session directory helpers ------------------------------------------

def session_dir_from_state(state: dict, workspace: Path) -> Path | None:
    out = state.get("output_dir")
    if not out:
        return None
    p = Path(out)
    return p if p.is_absolute() else (Path(workspace) / p)


def ensure_session_dirs(session_dir: Path) -> None:
    for sub in ("", "steps", "artifacts"):
        (session_dir / sub).mkdir(parents=True, exist_ok=True)


# --- Hashing -------------------------------------------------------------

def canonical_json(obj) -> str:
    """Stable serialization used as hash input (sorted keys, compact)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def record_hash(prev_sha256: str, record_without_hash: dict) -> str:
    payload = (prev_sha256 + canonical_json(record_without_hash)).encode("utf-8")
    return sha256_bytes(payload)


# --- Cross-platform file lock -------------------------------------------

class FileLock:
    """Atomic lock via O_CREAT|O_EXCL. Works on Windows + POSIX.

    Breaks a lock left behind by a dead process once it is older than `stale`.
    """

    def __init__(self, path, timeout: float = 15.0, poll: float = 0.05, stale: float = 60.0):
        self.path = str(path)
        self.timeout = timeout
        self.poll = poll
        self.stale = stale
        self.fd = None

    def __enter__(self):
        start = time.time()
        while True:
            try:
                self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self.fd, str(os.getpid()).encode())
                return self
            except FileExistsError:
                try:
                    if time.time() - os.path.getmtime(self.path) > self.stale:
                        os.unlink(self.path)
                        continue
                except OSError:
                    pass
                if time.time() - start > self.timeout:
                    raise TimeoutError(f"could not acquire lock: {self.path}")
                time.sleep(self.poll)

    def __exit__(self, *exc):
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
        try:
            os.unlink(self.path)
        except OSError:
            pass
        return False


# --- Chain head + append -------------------------------------------------

def _head_path(session_dir: Path) -> Path:
    return session_dir / "head.json"


def _log_path(session_dir: Path) -> Path:
    return session_dir / "log.jsonl"


def read_head(session_dir: Path) -> dict:
    return load_json(_head_path(session_dir), default={"seq": 0, "record_sha256": GENESIS_HASH})


def log_lock(session_dir: Path) -> "FileLock":
    """The lock guarding seq assignment + chain append for a session."""
    return FileLock(Path(session_dir) / ".log.lock")


def commit_record(session_dir: Path, record: dict, seq: int, prev: str) -> dict:
    """Chain + persist a record. Caller MUST already hold `log_lock`.

    Sets `seq`, `prev_sha256`, `record_sha256`, appends one JSONL line, and
    advances head.json. Returns the finalized record.
    """
    session_dir = Path(session_dir)
    record = dict(record)
    record.pop("record_sha256", None)
    record["seq"] = seq
    record["prev_sha256"] = prev
    rec_hash = record_hash(prev, record)
    record["record_sha256"] = rec_hash

    line = json.dumps(record, ensure_ascii=False)
    with open(_log_path(session_dir), "a", encoding="utf-8") as fh:
        fh.write(line + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    write_json(_head_path(session_dir), {"seq": seq, "record_sha256": rec_hash})
    return record


def append_record(session_dir: Path, record: dict) -> dict:
    """Assign seq + chain the record under the session lock, then append.

    Convenience wrapper for callers that don't need `seq` before the record is
    built. The capture hook instead holds `log_lock` itself so step/artifact
    filenames can use the reserved seq.
    """
    session_dir = Path(session_dir)
    with log_lock(session_dir):
        head = read_head(session_dir)
        return commit_record(session_dir, record,
                             int(head.get("seq", 0)) + 1,
                             head.get("record_sha256", GENESIS_HASH))


# --- Read / verify -------------------------------------------------------

def iter_records(session_dir: Path):
    log = _log_path(Path(session_dir))
    if not log.exists():
        return
    with open(log, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def verify_chain(session_dir: Path) -> dict:
    """Recompute the hash chain. Returns {ok, count, break_at, reason}."""
    prev = GENESIS_HASH
    count = 0
    for rec in iter_records(session_dir):
        count += 1
        seq = rec.get("seq")
        if rec.get("prev_sha256") != prev:
            return {"ok": False, "count": count, "break_at": seq,
                    "reason": "prev_sha256 mismatch (record inserted/removed/reordered)"}
        stored = rec.get("record_sha256")
        body = {k: v for k, v in rec.items() if k != "record_sha256"}
        expected = record_hash(rec.get("prev_sha256", GENESIS_HASH), body)
        if expected != stored:
            return {"ok": False, "count": count, "break_at": seq,
                    "reason": "record_sha256 mismatch (record content altered)"}
        prev = stored
    return {"ok": True, "count": count, "break_at": None, "reason": None}
