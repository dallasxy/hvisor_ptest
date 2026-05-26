#!/usr/bin/env python3
"""Run ptests after zone0_start from hvisor jenkins/ci_runner.py."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

from ci_config import get_bid_entry, load_ci, parse_bid

VALID_PTESTS = frozenset({"irq", "net", "mem", "blk"})

PTEST_BENCH: dict[str, tuple[str, str, float, str]] = {
    "mem": ("Memory", "./test/bench/bench_mem.sh", 600.0, "test/perfresult/bench_mem.txt"),
    "irq": ("IRQ", "./test/bench/bench_irq.sh", 180.0, "test/perfresult/bench_irq.txt"),
    "net": ("Network", "./test/bench/bench_net.sh", 180.0, "test/perfresult/bench_net.txt"),
}

HOME_DIR: dict[str, str] = {
    "aarch64/qemu-gicv3": "/home/arm64",
    "riscv64/qemu-plic": "/home/riscv64",
}


def setup_hvisor_jenkins(workspace: Path) -> None:
    jenkins_dir = workspace / "jenkins"
    if not (jenkins_dir / "ci_runner.py").is_file():
        raise SystemExit(f"hvisor jenkins scripts not found: {jenkins_dir}")
    path = str(jenkins_dir)
    if path not in sys.path:
        sys.path.insert(0, path)


def import_ci_runner():
    from ci_runner import (  # type: ignore[import-not-found]
        TerminalCommandError,
        TerminalTimeoutError,
        build_terminal,
        read_and_print_until_quiet,
        run_and_print_quiet,
        run_and_print_quiet_raw,
        run_and_print_send_only,
        terminate_managed_process,
        zone0_start,
    )

    return {
        "TerminalCommandError": TerminalCommandError,
        "TerminalTimeoutError": TerminalTimeoutError,
        "build_terminal": build_terminal,
        "read_and_print_until_quiet": read_and_print_until_quiet,
        "run_and_print_quiet": run_and_print_quiet,
        "run_and_print_quiet_raw": run_and_print_quiet_raw,
        "run_and_print_send_only": run_and_print_send_only,
        "terminate_managed_process": terminate_managed_process,
        "zone0_start": zone0_start,
    }


def make_runtime_config(workspace: Path, bid: str) -> dict[str, Any]:
    arch, board = parse_bid(bid)
    return {
        "bid": bid,
        "arch": arch,
        "board": board,
        "mode": "qemu",
        "workspace": workspace,
        "socket_path": str((workspace / ".qemu" / "qemu.sock").resolve()),
    }


def home_dir(cfg: dict[str, Any]) -> str:
    return HOME_DIR.get(cfg["bid"], f"/home/{cfg['arch']}")


def prepare_zone0_shell(cfg: dict[str, Any], term: Any, cr: dict[str, Any]) -> None:
    home = home_dir(cfg)
    run_quiet_raw = cr["run_and_print_quiet_raw"]
    run_quiet = cr["run_and_print_quiet"]

    _ = run_quiet_raw(term, "bash", quiet_seconds=1.0, max_duration=15.0)
    _, _ = run_quiet(term, f"cd {home}", quiet_seconds=1.0, max_duration=15.0)
    _, _ = run_quiet(
        term,
        "mkdir -p test/perfresult",
        quiet_seconds=1.0,
        max_duration=15.0,
    )
    _, _ = run_quiet(
        term,
        "mount -t proc proc /proc 2>/dev/null || true; "
        "mount -t sysfs sysfs /sys 2>/dev/null || true; "
        "mkdir -p /dev/shm; mount -t tmpfs tmpfs /dev/shm 2>/dev/null || true",
        quiet_seconds=1.0,
        max_duration=20.0,
    )


def run_zone0_bench(cfg: dict[str, Any], term: Any, ptest: str, cr: dict[str, Any]) -> None:
    name, cmd, timeout_sec, result_file = PTEST_BENCH[ptest]
    read_quiet = cr["read_and_print_until_quiet"]
    run_quiet = cr["run_and_print_quiet"]
    err_cls = cr["TerminalCommandError"]

    print(f"\n============ Zone0: {name} Benchmark ============\n", flush=True)
    term.send(cmd)
    output = read_quiet(term, quiet_seconds=3.0, max_duration=timeout_sec + 60.0)
    if "=== Done ===" not in output:
        raise err_cls(f"{name} bench did not print done marker")
    _, _ = run_quiet(
        term,
        f"echo '--- {name} result ---' && cat {result_file} 2>/dev/null || true",
        quiet_seconds=1.0,
        max_duration=30.0,
        check_exit=False,
    )


def run_blk_bench_in_zone1(cfg: dict[str, Any], term: Any, cr: dict[str, Any]) -> None:
    home = home_dir(cfg)
    run_quiet = cr["run_and_print_quiet"]
    run_quiet_raw = cr["run_and_print_quiet_raw"]
    run_send_only = cr["run_and_print_send_only"]
    read_quiet = cr["read_and_print_until_quiet"]
    err_cls = cr["TerminalCommandError"]

    print("\n============ Zone1: Virtio-BLK Benchmark ============\n", flush=True)
    _, _ = run_quiet(term, "insmod hvisor.ko", quiet_seconds=2.0, max_duration=30.0)
    _, boot_rc = run_quiet(
        term,
        "./boot_zone1.sh",
        quiet_seconds=15.0,
        max_duration=60.0,
    )
    if boot_rc != 0:
        raise err_cls("boot_zone1.sh failed")
    _ = run_quiet_raw(term, "bash", quiet_seconds=1.0, max_duration=15.0)
    _ = run_send_only(term, "./screen_zone1.sh", read_duration=5.0)
    _ = run_send_only(term, "\n", read_duration=2.0)
    _ = run_quiet_raw(term, "bash", quiet_seconds=1.0, max_duration=15.0)
    _, _ = run_quiet(term, f"cd {home}", quiet_seconds=1.0, max_duration=15.0)
    _, _ = run_quiet(
        term,
        "mkdir -p test/perfresult",
        quiet_seconds=1.0,
        max_duration=15.0,
    )
    term.send("./test/bench/bench_blk.sh")
    output = read_quiet(term, quiet_seconds=3.0, max_duration=360.0)
    if "=== Done ===" not in output:
        raise err_cls("blk bench did not print done marker")
    _, _ = run_quiet(
        term,
        "echo '--- blk result (zone1) ---' && cat test/perfresult/bench_blk.txt 2>/dev/null || true",
        quiet_seconds=1.0,
        max_duration=30.0,
        check_exit=False,
    )
    term._ensure_open()
    term.backend.write(b"\x01d")
    time.sleep(1.0)
    _, _ = run_quiet(
        term,
        "./hvisor zone shutdown -id 1",
        quiet_seconds=2.0,
        max_duration=30.0,
        check_exit=False,
    )


def run_ptests(cfg: dict[str, Any], ptests: list[str]) -> int:
    setup_hvisor_jenkins(cfg["workspace"])
    cr = import_ci_runner()
    zone0_start = cr["zone0_start"]
    build_terminal = cr["build_terminal"]
    terminate_managed_process = cr["terminate_managed_process"]
    timeout_err = cr["TerminalTimeoutError"]
    cmd_err = cr["TerminalCommandError"]

    zone0_tests = [p for p in ptests if p != "blk"]
    has_blk = "blk" in ptests

    print(
        f"\n============ hvisor ptests ({cfg['bid']}) "
        f"zone0_start + benchmarks ============\n",
        flush=True,
    )

    try:
        rc = zone0_start(cfg, None)
        if rc != 0:
            return rc

        with build_terminal(cfg) as term:
            prepare_zone0_shell(cfg, term, cr)
            for ptest in zone0_tests:
                print(f"\n--- running ptest={ptest} ---\n", flush=True)
                run_zone0_bench(cfg, term, ptest, cr)
            if has_blk:
                print("\n--- running ptest=blk ---\n", flush=True)
                run_blk_bench_in_zone1(cfg, term, cr)

        print("\n============ all ptests finished ============\n", flush=True)
        return 0
    except (timeout_err, cmd_err) as exc:
        print(f"[ptest_runner] failed: {exc}", flush=True)
        return 1
    finally:
        terminate_managed_process(cfg)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run ptests using hvisor jenkins/ci_runner.py zone0_start",
    )
    parser.add_argument("--bid", required=True, help="BID, e.g. aarch64/qemu-gicv3")
    parser.add_argument(
        "--ptests",
        required=True,
        help="Comma-separated: irq,net,mem,blk",
    )
    parser.add_argument(
        "--workspace",
        required=True,
        help="hvisor source tree (must contain jenkins/ci_runner.py)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ci = load_ci()
    _ = get_bid_entry(ci, args.bid)

    workspace = Path(args.workspace).resolve()
    if not workspace.is_dir():
        raise SystemExit(f"workspace not found: {workspace}")

    ptests = [p.strip() for p in args.ptests.split(",") if p.strip()]
    if not ptests:
        raise SystemExit("no ptests selected")

    bad = [p for p in ptests if p not in VALID_PTESTS]
    if bad:
        raise SystemExit(f"unsupported ptest(s): {bad}")

    cfg = make_runtime_config(workspace, args.bid)
    return run_ptests(cfg, ptests)


if __name__ == "__main__":
    raise SystemExit(main())
