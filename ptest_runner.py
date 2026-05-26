#!/usr/bin/env python3
"""Run ptests: zone0_start (imported) + benchmarks in one process."""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any

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


def parse_bid(bid: str) -> tuple[str, str]:
    parts = bid.strip().split("/", 1)
    if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
        raise ValueError(f"invalid BID: {bid!r}")
    return parts[0].strip(), parts[1].strip()


def setup_hvisor_jenkins(workspace: Path) -> None:
    jenkins_dir = workspace / "jenkins"
    if not (jenkins_dir / "ci_runner.py").is_file():
        raise SystemExit(f"hvisor jenkins scripts not found: {jenkins_dir}")
    path = str(jenkins_dir)
    if path in sys.path:
        sys.path.remove(path)
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
        wait_qemu_socket,
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
        "wait_qemu_socket": wait_qemu_socket,
        "zone0_start": zone0_start,
    }


def make_runtime_config(workspace: Path, bid: str) -> dict[str, Any]:
    setup_hvisor_jenkins(workspace)
    from ci_config import get_bid_entry, load_ci  # noqa: WPS433

    entry = get_bid_entry(load_ci(), bid)
    arch, board = parse_bid(bid)
    qemu_dir = workspace / ".qemu"
    qemu_dir.mkdir(parents=True, exist_ok=True)
    return {
        "bid": bid,
        "arch": arch,
        "board": board,
        "mode": str(entry.get("mode", "")).strip(),
        "workspace": workspace,
        "socket_path": str((qemu_dir / "qemu.sock").resolve()),
        "qemu_pid_path": str((qemu_dir / "qemu.pid").resolve()),
    }


def record_qemu_pid(cfg: dict[str, Any]) -> None:
    proc = cfg.get("_managed_proc")
    if proc is not None and proc.poll() is None:
        Path(cfg["qemu_pid_path"]).write_text(str(proc.pid), encoding="ascii")


def terminate_qemu(cfg: dict[str, Any], cr: dict[str, Any]) -> None:
    cr["terminate_managed_process"](cfg)
    pid_path = Path(cfg["qemu_pid_path"])
    if not pid_path.is_file():
        return
    try:
        pid = int(pid_path.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        pid_path.unlink(missing_ok=True)
        return
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    pid_path.unlink(missing_ok=True)


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


def run_ptests(
    cfg: dict[str, Any],
    ptests: list[str],
    *,
    skip_zone0: bool,
    terminate: bool,
) -> int:
    cr = import_ci_runner()
    zone0_start = cr["zone0_start"]
    build_terminal = cr["build_terminal"]
    wait_qemu_socket = cr["wait_qemu_socket"]
    timeout_err = cr["TerminalTimeoutError"]
    cmd_err = cr["TerminalCommandError"]

    zone0_tests = [p for p in ptests if p != "blk"]
    has_blk = "blk" in ptests

    print(f"\n============ hvisor ptests ({cfg['bid']}) ============\n", flush=True)

    try:
        if not skip_zone0:
            rc = zone0_start(cfg, None)
            if rc != 0:
                return rc
            record_qemu_pid(cfg)
            time.sleep(5.0)
        elif ptests:
            wait_qemu_socket(cfg["socket_path"], timeout=30.0)

        if not ptests:
            print("\n============ zone0_start finished (no benchmarks) ============\n", flush=True)
            return 0

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
        if terminate:
            terminate_qemu(cfg, cr)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run ptests: zone0_start (import) + benchmarks via qemu.sock",
    )
    parser.add_argument("--bid", required=True, help="BID, e.g. aarch64/qemu-gicv3")
    parser.add_argument(
        "--ptests",
        default="",
        help="Comma-separated: irq,net,mem,blk (empty = zone0_start only)",
    )
    parser.add_argument(
        "--workspace",
        required=True,
        help="hvisor source tree (clone with jenkins/ modules)",
    )
    parser.add_argument(
        "--skip-zone0",
        action="store_true",
        help="Skip zone0_start (QEMU must already be running)",
    )
    parser.add_argument(
        "--no-terminate",
        action="store_true",
        help="Leave QEMU running after benchmarks",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    workspace = Path(args.workspace).resolve()
    if not workspace.is_dir():
        raise SystemExit(f"workspace not found: {workspace}")

    ptests = [p.strip() for p in args.ptests.split(",") if p.strip()]

    bad = [p for p in ptests if p not in VALID_PTESTS]
    if bad:
        raise SystemExit(f"unsupported ptest(s): {bad}")

    cfg = make_runtime_config(workspace, args.bid)
    if not cfg["mode"]:
        raise SystemExit(f"BID={args.bid}: tests.mode missing in hvisor jenkins/ci.yaml")

    return run_ptests(
        cfg,
        ptests,
        skip_zone0=args.skip_zone0,
        terminate=not args.no_terminate,
    )


if __name__ == "__main__":
    raise SystemExit(main())
