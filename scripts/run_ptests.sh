#!/bin/sh
# Build hvisor in an existing clone, then run ptests via ptest_runner.py (uses hvisor jenkins/ci_runner.py).

set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)"

BID=""
PTESTS=""
HVISOR_SRC="${HVISOR_SRC:-${WORKSPACE:-${REPO_ROOT}}/hvisor-src}"
PREPARE_IMAGE="${PREPARE_IMAGE:-true}"
HVISOR_TOOL_URL="${HVISOR_TOOL_URL:-https://github.com/syswonder/hvisor-tool.git}"
HVISOR_TOOL_PATH="${HVISOR_TOOL_PATH:-hvisor-tool}"
SKIP_BUILD=false
BUILD_ONLY=false

usage() {
    echo "Usage: $0 --bid BID --ptests irq,net [--hvisor-src DIR] [--no-prepare-image] [--skip-build] [--build-only]"
    exit 1
}

while [ $# -gt 0 ]; do
    case "$1" in
        --bid) BID="$2"; shift 2 ;;
        --ptests) PTESTS="$2"; shift 2 ;;
        --hvisor-src) HVISOR_SRC="$2"; shift 2 ;;
        --no-prepare-image) PREPARE_IMAGE=false; shift ;;
        --skip-build) SKIP_BUILD=true; shift ;;
        --build-only) BUILD_ONLY=true; shift ;;
        -h|--help) usage ;;
        *) echo "unknown arg: $1"; usage ;;
    esac
done

[ -n "${BID}" ] || usage
if [ "${BUILD_ONLY}" != "true" ]; then
    [ -n "${PTESTS}" ] || usage
fi
[ -d "${HVISOR_SRC}" ] || { echo "ERROR: hvisor-src not found at ${HVISOR_SRC}; clone hvisor first"; exit 1; }
[ -f "${HVISOR_SRC}/jenkins/ci_runner.py" ] || { echo "ERROR: missing ${HVISOR_SRC}/jenkins/ci_runner.py"; exit 1; }

ARCH="${ARCH:-}"
BOARD="${BOARD:-}"
case "${BID}" in
    */*) ARCH="${ARCH:-$(echo "${BID}" | cut -d/ -f1)}"; BOARD="${BOARD:-$(echo "${BID}" | cut -d/ -f2)}" ;;
    *) echo "invalid BID: ${BID}"; exit 1 ;;
esac

# Same source as hvisor main Jenkins CI: hvisor-src/jenkins/ci.yaml via ci_config.py
load_bid_config() {
    local ci_runner="${HVISOR_SRC}/jenkins/ci_config.py"
    if [ ! -f "${ci_runner}" ]; then
        echo "ERROR: missing ${ci_runner}"
        exit 1
    fi
    local json
    json="$(python3 "${ci_runner}" get-bid --bid "${BID}")" || {
        echo "ERROR: BID=${BID} not found in ${HVISOR_SRC}/jenkins/ci.yaml"
        exit 1
    }
    KDIR="$(echo "${json}" | python3 -c "import sys,json; print(json.load(sys.stdin)['build_args'].get('KDIR',''))")"
    TARCH="$(echo "${json}" | python3 -c "import sys,json; print(json.load(sys.stdin)['build_args'].get('TARCH',''))")"
    if [ -z "${KDIR}" ]; then
        echo "ERROR: KDIR missing for BID=${BID} in ${HVISOR_SRC}/jenkins/ci.yaml"
        exit 1
    fi
    echo "=== BID config: KDIR=${KDIR} TARCH=${TARCH:-${ARCH}} ==="
}

load_bid_config
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

# Same as hvisor main Jenkinsfile "Prepare test" stage: copy pre-staged images from TEST_IMG_BASE.
stage_test_img() {
    TEST_IMG_BASE="${TEST_IMG_BASE:-/home/light/DEMO/syswonder/test_img}"
    external="${TEST_IMG_BASE}/${ARCH}/${BOARD}"
    configure="${HVISOR_SRC}/platform/${ARCH}/${BOARD}"

    if [ ! -d "${external}" ]; then
        echo "ERROR: TEST_IMG_BASE platform dir not found: ${external}"
        exit 1
    fi

    echo "=== Staging platform assets from ${external} ==="
    mkdir -p "${configure}"
    cp -r "${external}/." "${configure}/"

    # Makefile download-test-img expects flash.img at hvisor repo root; runner.sh uses the same path.
    if [ -f "${external}/flash.img" ]; then
        cp -f "${external}/flash.img" "${HVISOR_SRC}/flash.img"
    elif [ -f "${configure}/flash.img" ]; then
        cp -f "${configure}/flash.img" "${HVISOR_SRC}/flash.img"
    fi

    if [ -f "${HVISOR_SRC}/flash.img" ]; then
        echo "=== flash.img ready at ${HVISOR_SRC}/flash.img (skip wget download) ==="
    else
        echo "WARN: flash.img not found under ${external}; make may try network download"
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
    stage_test_img
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

if [ "${SKIP_BUILD}" != "true" ]; then
    build_hvisor
    build_hvisor_tool
    if [ "${PREPARE_IMAGE}" = "true" ]; then
        prepare_perf_image
    else
        echo "=== Skipping perf-prepare-img (PREPARE_IMAGE=false) ==="
        cd "${HVISOR_SRC}"
        stage_test_img
        toolchain_path_shell
        make test-pre ARCH="${ARCH}" BOARD="${BOARD}" MODE=release 2>/dev/null || true
        ./platform/"${ARCH}"/"${BOARD}"/test/systemtest/tcompiledtb.sh
        ./platform/"${ARCH}"/"${BOARD}"/test/perftest/trootfs_deploy.sh
    fi
fi

if [ "${BUILD_ONLY}" = "true" ]; then
    echo "=== Build-only mode, skipping ptest execution ==="
    exit 0
fi

echo "=== Running ptests (zone0_start via hvisor jenkins/ci_runner.py) ==="
export TERM="${TERM:-xterm}"
if ! python3 "${REPO_ROOT}/ptest_runner.py" \
    --bid "${BID}" \
    --ptests "${PTESTS}" \
    --workspace "${HVISOR_SRC}"; then
    exit 1
fi

copy_perf_artifacts
echo "=== All selected ptests passed ==="
