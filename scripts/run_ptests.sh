#!/bin/sh
# Clone hvisor, build, optionally prepare perf image, run selected ptests via ptest_runner.py.

set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)"

BID=""
PTESTS=""
HVISOR_REPO="${HVISOR_REPO:-https://github.com/syswonder/hvisor.git}"
HVISOR_BRANCH="${HVISOR_BRANCH:-main}"
HVISOR_SRC="${HVISOR_SRC:-${WORKSPACE:-${REPO_ROOT}}/hvisor-src}"
PREPARE_IMAGE="${PREPARE_IMAGE:-true}"
HVISOR_TOOL_URL="${HVISOR_TOOL_URL:-https://github.com/syswonder/hvisor-tool.git}"
HVISOR_TOOL_PATH="${HVISOR_TOOL_PATH:-hvisor-tool}"

usage() {
    echo "Usage: $0 --bid BID --ptests irq,net [--repo URL] [--branch BRANCH] [--hvisor-src DIR] [--no-prepare-image]"
    exit 1
}

while [ $# -gt 0 ]; do
    case "$1" in
        --bid) BID="$2"; shift 2 ;;
        --ptests) PTESTS="$2"; shift 2 ;;
        --repo) HVISOR_REPO="$2"; shift 2 ;;
        --branch) HVISOR_BRANCH="$2"; shift 2 ;;
        --hvisor-src) HVISOR_SRC="$2"; shift 2 ;;
        --no-prepare-image) PREPARE_IMAGE=false; shift ;;
        -h|--help) usage ;;
        *) echo "unknown arg: $1"; usage ;;
    esac
done

[ -n "${BID}" ] || usage
[ -n "${PTESTS}" ] || usage

ARCH="${ARCH:-}"
BOARD="${BOARD:-}"
case "${BID}" in
    */*) ARCH="${ARCH:-$(echo "${BID}" | cut -d/ -f1)}"; BOARD="${BOARD:-$(echo "${BID}" | cut -d/ -f2)}" ;;
    *) echo "invalid BID: ${BID}"; exit 1 ;;
esac

# shellcheck source=/dev/null
if [ -f "${REPO_ROOT}/ci.yaml" ]; then
    KDIR="$(python3 "${REPO_ROOT}/ci_config.py" get-bid --bid "${BID}" 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin)['build_args'].get('KDIR',''))" || true)"
    TARCH="$(python3 "${REPO_ROOT}/ci_config.py" get-bid --bid "${BID}" 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin)['build_args'].get('TARCH',''))" || true)"
fi
KDIR="${KDIR:-}"
TARCH="${TARCH:-${ARCH}}"

normalize_tool_arch() {
    case "$1" in
        aarch64|arm64) echo arm64 ;;
        riscv64|riscv) echo riscv ;;
        loongarch64|loongarch) echo loongarch ;;
        *) echo "$1" ;;
    esac
}
TARCH="$(normalize_tool_arch "${TARCH}")"

toolchain_path_shell() {
    if [ -n "${TOOLCHAIN_PATHS:-}" ]; then
        export PATH="${CARGO_HOME:-/usr/local/cargo}/bin:${TOOLCHAIN_PATHS}:${PATH}"
    else
        export PATH="${CARGO_HOME:-/usr/local/cargo}/bin:${PATH}"
    fi
}

qemu_path_shell() {
    if [ -n "${QEMU_PATH:-}" ]; then
        export PATH="${QEMU_PATH}:${PATH}"
    fi
}

clone_hvisor() {
    if [ -d "${HVISOR_SRC}/.git" ]; then
        echo "=== Updating hvisor at ${HVISOR_SRC} (branch ${HVISOR_BRANCH}) ==="
        git -C "${HVISOR_SRC}" fetch --depth 1 origin "${HVISOR_BRANCH}" || git -C "${HVISOR_SRC}" fetch origin
        git -C "${HVISOR_SRC}" checkout "${HVISOR_BRANCH}"
        git -C "${HVISOR_SRC}" pull --ff-only origin "${HVISOR_BRANCH}" 2>/dev/null || true
    else
        echo "=== Cloning hvisor into ${HVISOR_SRC} ==="
        mkdir -p "$(dirname "${HVISOR_SRC}")"
        git clone --depth 1 --branch "${HVISOR_BRANCH}" "${HVISOR_REPO}" "${HVISOR_SRC}"
    fi
}

build_hvisor() {
    echo "=== Building hvisor ARCH=${ARCH} BOARD=${BOARD} ==="
    cd "${HVISOR_SRC}"
    toolchain_path_shell
    qemu_path_shell
    export TERM="${TERM:-xterm}"

    chmod +x tools/kconfig/bootstrap_venv.sh tools/kconfig/host_config.sh 2>/dev/null || true
    if [ ! -x tools/kconfig/.venv/bin/python ]; then
        ./tools/kconfig/bootstrap_venv.sh
    fi
    make defconfig ARCH="${ARCH}" BOARD="${BOARD}"
    if [ "${ARCH}" != "x86_64" ]; then
        make dtb ARCH="${ARCH}" BOARD="${BOARD}"
    fi
    make all ARCH="${ARCH}" BOARD="${BOARD}" MODE=release
}

build_hvisor_tool() {
    if [ -z "${KDIR}" ]; then
        echo "ERROR: KDIR not set for BID=${BID}; check ci.yaml"
        exit 1
    fi
    echo "=== Building hvisor-tool TARCH=${TARCH} KDIR=${KDIR} ==="
    cd "${HVISOR_SRC}"
    toolchain_path_shell
    if [ ! -d "${HVISOR_TOOL_PATH}/.git" ]; then
        mkdir -p "${HVISOR_TOOL_PATH}"
        git clone --depth 1 "${HVISOR_TOOL_URL}" "${HVISOR_TOOL_PATH}"
    fi
    make -C "${HVISOR_TOOL_PATH}" all ARCH="${TARCH}" KDIR="${KDIR}"
}

prepare_perf_image() {
    echo "=== Preparing perf image (perf-prepare-img) ==="
    cd "${HVISOR_SRC}"
    toolchain_path_shell
    qemu_path_shell
    make perf-prepare-img ARCH="${ARCH}" BOARD="${BOARD}" MODE=release
}

copy_perf_artifacts() {
    ART_DIR="${REPO_ROOT}/artifacts/${BID//\//__}"
    mkdir -p "${ART_DIR}"
    ROOTFS_EXT4="${HVISOR_SRC}/platform/${ARCH}/${BOARD}/image/virtdisk/rootfs1.ext4"
    MNT="${HVISOR_SRC}/platform/${ARCH}/${BOARD}/image/virtdisk/rootfs"
    HOME_SUB=""
    case "${BID}" in
        aarch64/qemu-gicv3) HOME_SUB="arm64" ;;
        riscv64/qemu-plic) HOME_SUB="riscv64" ;;
    esac
    if [ ! -f "${ROOTFS_EXT4}" ] || [ -z "${HOME_SUB}" ]; then
        return 0
    fi
    sudo mkdir -p "${MNT}"
    if mountpoint -q "${MNT}" 2>/dev/null; then
        sudo umount "${MNT}" || true
    fi
    if sudo mount -t ext4 "${ROOTFS_EXT4}" "${MNT}" 2>/dev/null; then
        PERF_SRC="${MNT}/home/${HOME_SUB}/test/perfresult"
        if [ -d "${PERF_SRC}" ]; then
            sudo cp -a "${PERF_SRC}/." "${ART_DIR}/" 2>/dev/null || true
            sudo chown -R "$(id -u):$(id -g)" "${ART_DIR}" 2>/dev/null || true
        fi
        sudo umount "${MNT}" || true
    fi
}

clone_hvisor
build_hvisor
build_hvisor_tool

if [ "${PREPARE_IMAGE}" = "true" ]; then
    prepare_perf_image
else
    echo "=== Skipping perf-prepare-img (PREPARE_IMAGE=false) ==="
    cd "${HVISOR_SRC}"
    toolchain_path_shell
    make test-pre ARCH="${ARCH}" BOARD="${BOARD}" MODE=release 2>/dev/null || true
    ./platform/"${ARCH}"/"${BOARD}"/test/systemtest/tcompiledtb.sh
    ./platform/"${ARCH}"/"${BOARD}"/test/perftest/trootfs_deploy.sh
fi

OLD_IFS="${IFS}"
IFS=,
# shellcheck disable=SC2086
set -- ${PTESTS}
IFS="${OLD_IFS}"

FAILED=0
for ptest in "$@"; do
    ptest="$(echo "${ptest}" | tr -d ' ')"
    [ -n "${ptest}" ] || continue
    echo "=== Running ptest=${ptest} ==="
    if ! python3 "${REPO_ROOT}/ptest_runner.py" \
        --bid "${BID}" \
        --ptest "${ptest}" \
        --workspace "${HVISOR_SRC}"; then
        FAILED=1
    fi
    sleep 2
done

copy_perf_artifacts

if [ "${FAILED}" -ne 0 ]; then
    echo "=== One or more ptests failed ==="
    exit 1
fi
echo "=== All selected ptests passed ==="
