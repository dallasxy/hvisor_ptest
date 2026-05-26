#!/usr/bin/env python3
"""Run a single ptest benchmark via make ci-run and QEMU UNIX socket."""

from __future__ import annotations

import argparse
import os
import signal
import socket
import subprocess
import time
from pathlib import Path
from typing import Any

from ci_config import get_bid_entry, load_ci, parse_bid
from terminal import Terminal, TerminalCommandError, TerminalTimeoutError

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


def wait_qemu_socket(path: str, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if Path(path).exists():
            try:
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                sock.settimeout(0.5)
                sock.connect(path)
                sock.close()
                return
            except OSError:
                pass
        time.sleep(0.2)
    raise SystemExit(f"qemu socket not ready: {path}")


def terminate_managed_process(cfg: dict[str, Any]) -> None:
    proc = cfg.get("_managed_proc")
    if proc is None or proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def run_and_print_quiet(
    term: Terminal,
    command: str,
    quiet_seconds: float = 1.0,
    max_duration: float = 30.0,
    check_exit: bool = True,
) -> tuple[str, int]:
    output, rc = term.run_until_quiet_with_status(
        command,
        quiet_seconds=quiet_seconds,
        max_duration=max_duration,
    )
    if output:
        print(output, end="", flush=True)
    if check_exit and rc != 0:
        raise TerminalCommandError(f"command failed with rc={rc}: {command}")
    return output, rc


def run_and_print_quiet_raw(
    term: Terminal,
    command: str,
    quiet_seconds: float = 1.0,
    max_duration: float = 30.0,
) -> str:
    output = term.send_until_quiet(
        command,
        quiet_seconds=quiet_seconds,
        max_duration=max_duration,
    )
    if output:
        print(output, end="", flush=True)
    return output


def read_and_print_until_quiet(
    term: Terminal,
    quiet_seconds: float = 3.0,
    max_duration: float = 120.0,
) -> str:
    output = term.read_until_quiet(
        quiet_seconds=quiet_seconds,
        max_duration=max_duration,
    )
    if output:
        print(output, end="", flush=True)
    return output


def run_and_print_send_only(
    term: Terminal,
    command: str,
    read_duration: float = 0.5,
) -> str:
    output = term.send_and_drain(command, read_duration=read_duration)
    if output:
        print(output, end="", flush=True)
    return output


def home_dir(cfg: dict[str, Any]) -> str:
    return HOME_DIR.get(cfg["bid"], f"/home/{cfg['arch']}")


def boot_zone0(cfg: dict[str, Any], term: Terminal) -> None:
    bid = cfg["bid"]
    if bid == "aarch64/qemu-gicv3":
        _ = read_and_print_until_quiet(term, quiet_seconds=3.0, max_duration=15.0)
        term.send("bootm 0x40400000 - 0x40000000")
        _ = read_and_print_until_quiet(term, quiet_seconds=5.0, max_duration=180.0)
        return
    if bid == "riscv64/qemu-plic":
        _ = read_and_print_until_quiet(term, quiet_seconds=5.0, max_duration=180.0)
        return
    raise SystemExit(f"unsupported BID for ptest: {bid}")


def prepare_zone0_shell(cfg: dict[str, Any], term: Terminal) -> None:
    home = home_dir(cfg)
    _ = run_and_print_quiet_raw(term, "bash", quiet_seconds=1.0, max_duration=15.0)
    _, _ = run_and_print_quiet(term, f"cd {home}", quiet_seconds=1.0, max_duration=15.0)
    _, _ = run_and_print_quiet(
        term,
        "mkdir -p test/perfresult",
        quiet_seconds=1.0,
        max_duration=15.0,
    )
    _, _ = run_and_print_quiet(
        term,
        "mount -t proc proc /proc 2>/dev/null || true; "
        "mount -t sysfs sysfs /sys 2>/dev/null || true; "
        "mkdir -p /dev/shm; mount -t tmpfs tmpfs /dev/shm 2>/dev/null || true",
        quiet_seconds=1.0,
        max_duration=20.0,
    )


def run_zone0_bench(cfg: dict[str, Any], term: Terminal, ptest: str) -> None:
    name, cmd, timeout_sec, result_file = PTEST_BENCH[ptest]
    print(f"\n============ Zone0: {name} Benchmark ============\n", flush=True)
    term.send(cmd)
    output = read_and_print_until_quiet(
        term,
        quiet_seconds=3.0,
        max_duration=timeout_sec + 60.0,
    )
    if "=== Done ===" not in output:
        raise TerminalCommandError(f"{name} bench did not print done marker")
    _, _ = run_and_print_quiet(
        term,
        f"echo '--- {name} result ---' && cat {result_file} 2>/dev/null || true",
        quiet_seconds=1.0,
        max_duration=30.0,
        check_exit=False,
    )


def run_blk_bench_in_zone1(cfg: dict[str, Any], term: Terminal) -> None:
    home = home_dir(cfg)
    print("\n============ Zone1: Virtio-BLK Benchmark ============\n", flush=True)
    _, _ = run_and_print_quiet(term, "insmod hvisor.ko", quiet_seconds=2.0, max_duration=30.0)
    _, boot_rc = run_and_print_quiet(
        term,
        "./boot_zone1.sh",
        quiet_seconds=15.0,
        max_duration=60.0,
    )
    if boot_rc != 0:
        raise TerminalCommandError("boot_zone1.sh failed")
    _ = run_and_print_quiet_raw(term, "bash", quiet_seconds=1.0, max_duration=15.0)
    _ = run_and_print_send_only(term, "./screen_zone1.sh", read_duration=5.0)
    _ = run_and_print_send_only(term, "\n", read_duration=2.0)
    _ = run_and_print_quiet_raw(term, "bash", quiet_seconds=1.0, max_duration=15.0)
    _, _ = run_and_print_quiet(term, f"cd {home}", quiet_seconds=1.0, max_duration=15.0)
    _, _ = run_and_print_quiet(
        term,
        "mkdir -p test/perfresult",
        quiet_seconds=1.0,
        max_duration=15.0,
    )
    term.send("./test/bench/bench_blk.sh")
    output = read_and_print_until_quiet(term, quiet_seconds=3.0, max_duration=360.0)
    if "=== Done ===" not in output:
        raise TerminalCommandError("blk bench did not print done marker")
    _, _ = run_and_print_quiet(
        term,
        "echo '--- blk result (zone1) ---' && cat test/perfresult/bench_blk.txt 2>/dev/null || true",
        quiet_seconds=1.0,
        max_duration=30.0,
        check_exit=False,
    )
    term._ensure_open()
    term.backend.write(b"\x01d")
    time.sleep(1.0)
    _, _ = run_and_print_quiet(
        term,
        "./hvisor zone shutdown -id 1",
        quiet_seconds=2.0,
        max_duration=30.0,
        check_exit=False,
    )


def run_ptest(cfg: dict[str, Any], ptest: str) -> int:
    if ptest not in VALID_PTESTS:
        raise SystemExit(f"unsupported ptest: {ptest!r}, use irq|net|mem|blk")

    print(
        f"\n============ hvisor ptest ({cfg['bid']}, ptest={ptest}) "
        f"via ci-run ============\n",
        flush=True,
    )

    cmd = [
        "make",
        f"ARCH={cfg['arch']}",
        f"BOARD={cfg['board']}",
        "MODE=release",
        "ci-run",
    ]
    proc = subprocess.Popen(cmd, cwd=cfg["workspace"], start_new_session=True)
    cfg["_managed_proc"] = proc

    try:
        wait_qemu_socket(cfg["socket_path"], timeout=60.0)
        with Terminal.from_qemu_socket(path=cfg["socket_path"]) as term:
            boot_zone0(cfg, term)
            prepare_zone0_shell(cfg, term)
            if ptest == "blk":
                run_blk_bench_in_zone1(cfg, term)
            else:
                run_zone0_bench(cfg, term, ptest)
        print(f"\n============ ptest={ptest} finished ============\n", flush=True)
        return 0
    except (TerminalTimeoutError, TerminalCommandError) as exc:
        print(f"[ptest_runner] failed: {exc}", flush=True)
        return 1
    finally:
        terminate_managed_process(cfg)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one ptest via make ci-run + qemu.sock")
    parser.add_argument("--bid", required=True, help="BID in ci.yaml, e.g. aarch64/qemu-gicv3")
    parser.add_argument("--ptest", required=True, help="irq|net|mem|blk")
    parser.add_argument(
        "--workspace",
        required=True,
        help="hvisor source tree (clone/build directory)",
    )
    return parser.parse_args()


def load_runtime_config(args: argparse.Namespace) -> dict[str, Any]:
    ci = load_ci()
    _ = get_bid_entry(ci, args.bid)
    try:
        arch, board = parse_bid(args.bid)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    workspace = Path(args.workspace).resolve()
    if not workspace.is_dir():
        raise SystemExit(f"workspace not found: {workspace}")

    return {
        "bid": args.bid,
        "arch": arch,
        "board": board,
        "workspace": workspace,
        "socket_path": str((workspace / ".qemu" / "qemu.sock").resolve()),
    }


def main() -> int:
    args = parse_args()
    cfg = load_runtime_config(args)
    return run_ptest(cfg, args.ptest.strip())


if __name__ == "__main__":
    raise SystemExit(main())
