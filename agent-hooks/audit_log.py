#!/usr/bin/env python3
"""
Append one NDJSON audit line per hook invocation for Cursor or Claude Code.

Config defaults to audit_config.json next to this script (single source for paths
and redaction). Override with AUDIT_HOOK_CONFIG=/path/to/audit_config.json.

Hook commands must pass --format and --phase. Script never writes to stdout
(so it does not alter tool calls). Exits 0 on parse/config errors (fail open).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path
from typing import Any


def _expand(path: str) -> Path:
    return Path(os.path.expanduser(path)).expanduser().resolve()


def _load_config(explicit: Path | None) -> dict[str, Any]:
    env_path = os.environ.get("AUDIT_HOOK_CONFIG", "").strip()
    if explicit is not None:
        cfg_path = explicit
    elif env_path:
        cfg_path = Path(env_path).expanduser()
    else:
        cfg_path = Path(__file__).resolve().parent / "audit_config.json"
    try:
        raw = cfg_path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def _should_redact_key(key: str, substrings: list[str]) -> bool:
    lower = key.lower()
    return any(s in lower for s in substrings)


def _sanitize(
    value: Any,
    *,
    redact_substrings: list[str],
    omit_keys: set[str],
    max_string_chars: int,
) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if k in omit_keys:
                continue
            if _should_redact_key(str(k), redact_substrings):
                out[k] = "[REDACTED]"
            else:
                out[k] = _sanitize(
                    v,
                    redact_substrings=redact_substrings,
                    omit_keys=omit_keys,
                    max_string_chars=max_string_chars,
                )
        return out
    if isinstance(value, list):
        return [
            _sanitize(
                i,
                redact_substrings=redact_substrings,
                omit_keys=omit_keys,
                max_string_chars=max_string_chars,
            )
            for i in value
        ]
    if isinstance(value, str):
        if len(value) > max_string_chars:
            return value[:max_string_chars] + f"...[truncated,{len(value)}chars]"
        return value
    return value


def _cap_record_bytes(obj: dict[str, Any], max_bytes: int) -> dict[str, Any]:
    raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    if len(raw.encode("utf-8")) <= max_bytes:
        return obj
    return {
        "ts": obj.get("ts"),
        "product": obj.get("product"),
        "phase": obj.get("phase"),
        "truncated": True,
        "note": "record exceeded max_record_bytes after redaction",
    }


def _append_line(log_file: Path, line: str) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
        fh.flush()


def main() -> None:
    parser = argparse.ArgumentParser(description="NDJSON audit sink for agent hooks.")
    parser.add_argument("--format", choices=("cursor", "claude"), required=True)
    parser.add_argument(
        "--phase",
        choices=("pre", "post", "failure"),
        required=True,
        help="pre=PreToolUse, post=PostToolUse, failure=postToolUseFailure / Claude equivalent.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Optional path to audit_config.json (else AUDIT_HOOK_CONFIG or default beside script).",
    )
    args = parser.parse_args()

    cfg = _load_config(args.config)
    paths = cfg.get("log_paths") or {}
    if not isinstance(paths, dict):
        sys.exit(0)
    key = "cursor" if args.format == "cursor" else "claude"
    raw_path = paths.get(key)
    if not isinstance(raw_path, str) or not raw_path.strip():
        sys.exit(0)
    log_file = _expand(raw_path)

    omit = cfg.get("omit_keys")
    omit_keys = set(omit) if isinstance(omit, list) else set()
    redact_raw = cfg.get("redact_key_substrings")
    redact_substrings = [s.lower() for s in redact_raw if isinstance(s, str)] if isinstance(redact_raw, list) else []
    max_string = int(cfg.get("max_string_chars", 8000))
    max_record = int(cfg.get("max_record_bytes", 524288))

    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        sys.exit(0)
    if not isinstance(payload, dict):
        sys.exit(0)

    sanitized = _sanitize(
        payload,
        redact_substrings=redact_substrings,
        omit_keys=omit_keys,
        max_string_chars=max_string,
    )
    record = {
        "ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "product": args.format,
        "phase": args.phase,
        "payload": sanitized,
    }
    record = _cap_record_bytes(record, max_record)

    try:
        _append_line(log_file, json.dumps(record, ensure_ascii=False, separators=(",", ":")))
    except OSError:
        sys.exit(0)
    sys.exit(0)


if __name__ == "__main__":
    main()
