#!/usr/bin/env python3
"""Read BID config by importing hvisor jenkins/ci_config (no subprocess to external scripts)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def setup_hvisor_jenkins(workspace: Path) -> None:
    jenkins_dir = workspace / "jenkins"
    if not (jenkins_dir / "ci_config.py").is_file():
        raise SystemExit(f"hvisor jenkins not found: {jenkins_dir}")
    path = str(jenkins_dir)
    if path in sys.path:
        sys.path.remove(path)
    sys.path.insert(0, path)


def normalize_tool_arch(arch: str) -> str:
    mapping = {
        "aarch64": "arm64",
        "arm64": "arm64",
        "riscv64": "riscv",
        "riscv": "riscv",
        "loongarch64": "loongarch",
        "loongarch": "loongarch",
    }
    return mapping.get(arch.strip(), arch.strip())


def get_bid_info(workspace: Path, bid: str) -> dict[str, str]:
    setup_hvisor_jenkins(workspace)
    from ci_config import get_bid_entry, load_ci, parse_bid  # noqa: WPS433

    entry = get_bid_entry(load_ci(), bid)
    arch, _board = parse_bid(bid)
    build_args = entry.get("build_args") or {}
    tests = entry.get("tests") or {}
    kdir = str(build_args.get("KDIR", "")).strip()
    tarch = normalize_tool_arch(str(build_args.get("TARCH", "") or arch))
    mode = str(entry.get("mode") or tests.get("mode", "")).strip()
    return {
        "bid": bid,
        "arch": arch,
        "KDIR": kdir,
        "TARCH": tarch,
        "mode": mode,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Print BID build/test config as JSON")
    parser.add_argument("--bid", required=True)
    parser.add_argument("--hvisor-src", required=True, help="cloned hvisor tree")
    args = parser.parse_args()

    workspace = Path(args.hvisor_src).resolve()
    if not workspace.is_dir():
        raise SystemExit(f"workspace not found: {workspace}")

    info = get_bid_info(workspace, args.bid)
    print(json.dumps(info))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
