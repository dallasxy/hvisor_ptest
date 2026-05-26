#!/usr/bin/env python3
"""Read ci.yaml for BID and build metadata (stdlib only, no PyYAML)."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DEFAULT_CI_YAML = ROOT / "ci.yaml"

BID_RE = re.compile(r"^\s*-\s*bid:\s*(.+?)\s*$")
KDIR_COLON_RE = re.compile(r"^\s*KDIR:\s*(.+?)\s*$")
KDIR_EQ_RE = re.compile(r"^\s*-\s*KDIR=(.+?)\s*$")
TARCH_COLON_RE = re.compile(r"^\s*TARCH:\s*(.+?)\s*$")
TARCH_EQ_RE = re.compile(r"^\s*-\s*TARCH=(.+?)\s*$")


def parse_bid(bid: str) -> tuple[str, str]:
    parts = bid.strip().split("/", 1)
    if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
        raise ValueError(f"invalid BID: {bid!r}")
    return parts[0].strip(), parts[1].strip()


def parse_ci_yaml_text(text: str) -> dict[str, Any]:
    bids: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    in_build_args = False

    for line in text.splitlines():
        bid_match = BID_RE.match(line)
        if bid_match:
            if current:
                bids.append(current)
            current = {"bid": bid_match.group(1).strip(), "build_args": {}}
            in_build_args = False
            continue

        if current is None:
            continue

        stripped = line.strip()
        if stripped == "build_args:":
            in_build_args = True
            continue

        if in_build_args:
            if stripped and not line.startswith((" ", "\t")) and not stripped.startswith("-"):
                in_build_args = False
            else:
                for pattern, key in (
                    (KDIR_COLON_RE, "KDIR"),
                    (KDIR_EQ_RE, "KDIR"),
                    (TARCH_COLON_RE, "TARCH"),
                    (TARCH_EQ_RE, "TARCH"),
                ):
                    match = pattern.match(line)
                    if match:
                        current["build_args"][key] = match.group(1).strip()
                continue

        if stripped.startswith("- bid:"):
            continue

    if current:
        bids.append(current)

    return {"bids": bids}


def load_ci(ci_yaml: Path | None = None) -> dict[str, Any]:
    path = ci_yaml or Path(os.environ.get("CI_YAML", DEFAULT_CI_YAML))
    if not path.exists():
        raise RuntimeError(f"missing ci config: {path}")
    data = parse_ci_yaml_text(path.read_text(encoding="utf-8"))
    if not isinstance(data.get("bids"), list):
        raise RuntimeError(f"{path}: 'bids' must be a list")
    return data


def list_bids(data: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for item in data.get("bids", []):
        bid = str((item or {}).get("bid", "")).strip()
        if bid:
            out.append(bid)
    return out


def get_bid_entry(data: dict[str, Any], bid: str) -> dict[str, Any]:
    for item in data.get("bids", []):
        entry = item or {}
        if str(entry.get("bid", "")).strip() == bid:
            build_args = entry.get("build_args") or {}
            if not isinstance(build_args, dict):
                build_args = {}
            return {
                "bid": bid,
                "build_args": {str(k): str(v) for k, v in build_args.items()},
            }
    raise RuntimeError(f"bid not found in ci.yaml: {bid}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read ci.yaml")
    parser.add_argument("--ci-file", help="Path to ci.yaml (default: ./ci.yaml or CI_YAML env)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list-bids", help="List all BID entries")
    get_parser = sub.add_parser("get-bid", help="Get one BID config")
    get_parser.add_argument("--bid", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ci_path = Path(args.ci_file) if args.ci_file else None
    data = load_ci(ci_path)
    if args.command == "list-bids":
        print(json.dumps({"bids": list_bids(data)}))
        return 0
    if args.command == "get-bid":
        print(json.dumps(get_bid_entry(data, args.bid)))
        return 0
    raise RuntimeError(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
