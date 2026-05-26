/** Active Choices Plugin v2 (uno-choice): PT_CHECKBOX multi-select for ptests. */
def normalizePtests(raw) {
    if (raw == null) {
        return []
    }
    if (raw instanceof List || raw instanceof String[]) {
        return raw.collect { it.toString().trim() }.findAll { it }
    }
    return raw.toString().split(',').collect { it.toString().trim() }.findAll { it }
}

def parseBid(String bid) {
    def parts = (bid ?: '').split('/', 2)
    if (parts.size() != 2 || !parts[0] || !parts[1]) {
        error("invalid BID: ${bid}")
    }
    return [arch: parts[0], board: parts[1]]
}

def toolchainPathShell() {
    return "export PATH=${env.CARGO_HOME}/bin:${env.TOOLCHAIN_PATHS}:\$PATH"
}

def qemuPathShell() {
    return "export PATH=${env.QEMU_PATH}:\$PATH"
}

properties([
    parameters([
        [
            $class: 'ChoiceParameter',
            choiceType: 'PT_CHECKBOX',
            description: 'Optional: select ptest benchmarks; leave empty for zone0_start only',
            name: 'PTESTS',
            script: [
                $class: 'GroovyScript',
                fallbackScript: [
                    classpath: [],
                    sandbox: true,
                    script: 'return ["irq", "net", "mem", "blk"]',
                ],
                script: [
                    classpath: [],
                    sandbox: true,
                    script: 'return ["irq", "net", "mem", "blk"]',
                ],
            ],
        ],
        choice(
            name: 'BID',
            choices: ['aarch64/qemu-gicv3', 'riscv64/qemu-plic'],
            description: 'Target platform (ARCH/BOARD)',
        ),
        string(
            name: 'HVISOR_REPO',
            defaultValue: 'https://github.com/dallasxy/hvisor.git',
            description: 'hvisor Git repository URL',
        ),
        string(
            name: 'HVISOR_BRANCH',
            defaultValue: 'config_refactor',
            description: 'hvisor branch or tag to clone',
        ),
    ]),
])

pipeline {
    agent any

    options {
        timestamps()
        disableConcurrentBuilds()
    }

    environment {
        HVISOR_SRC = "${WORKSPACE}/hvisor-src"
        HVISOR_TOOL_URL = 'https://github.com/syswonder/hvisor-tool.git'
        HVISOR_TOOL_PATH = 'hvisor-tool'
        TEST_IMG_BASE = '/home/light/DEMO/syswonder/test_img'
        RUST_HOME = '/usr/local/rustup'
        CARGO_HOME = '/usr/local/cargo'
        QEMU_PATH = '/home/light/DEMO/qemu-9.2.3/build'
        RISCV_TOOLCHAIN_PATH = '/home/light/DEMO/toolchain/riscv64-glibc-ubuntu-24.04-gcc'
        AARCH64_TOOLCHAIN_PATH = '/home/light/DEMO/toolchain/gcc-arm-10.3-2021.07-x86_64-aarch64-none-linux-gnu'
        LOONGARCH64_TOOLCHAIN_PATH = '/home/light/DEMO/toolchain/loongarch_cross_tools'
        TOOLCHAIN_PATHS = "${env.RISCV_TOOLCHAIN_PATH}/bin:${env.AARCH64_TOOLCHAIN_PATH}/bin:${env.LOONGARCH64_TOOLCHAIN_PATH}/bin"
    }

    stages {
        stage('Validate') {
            steps {
                script {
                    def selected = normalizePtests(params.PTESTS)
                    if (!selected.isEmpty()) {
                        def valid = ['irq', 'net', 'mem', 'blk'] as Set
                        def bad = selected.findAll { !valid.contains(it) }
                        if (!bad.isEmpty()) {
                            error("Invalid ptest(s): ${bad.join(', ')}; use irq|net|mem|blk")
                        }
                    }
                    env.SELECTED_PTESTS = selected.join(',')
                    echo "BID=${params.BID} PTESTS=${env.SELECTED_PTESTS ?: '(none, zone0 only)'} BRANCH=${params.HVISOR_BRANCH}"
                }
            }
        }

        stage('Clone hvisor') {
            steps {
                withEnv([
                    "HVISOR_SRC=${env.HVISOR_SRC}",
                    "HVISOR_REPO=${params.HVISOR_REPO}",
                    "HVISOR_BRANCH=${params.HVISOR_BRANCH}",
                ]) {
                    sh '''
                    set -eu
                    export HVISOR_SRC="${HVISOR_SRC:?}"
                    export HVISOR_REPO="${HVISOR_REPO:?}"
                    export HVISOR_BRANCH="${HVISOR_BRANCH:?}"

                    fresh_clone() {
                        echo "=== Cloning hvisor: ${HVISOR_REPO} @ ${HVISOR_BRANCH} ==="
                        rm -rf "${HVISOR_SRC}"
                        git clone --depth 1 --branch "${HVISOR_BRANCH}" "${HVISOR_REPO}" "${HVISOR_SRC}"
                    }

                    if [ -d "${HVISOR_SRC}/.git" ]; then
                        current_url="$(git -C "${HVISOR_SRC}" remote get-url origin 2>/dev/null || true)"
                        if [ "${current_url}" != "${HVISOR_REPO}" ]; then
                            echo "=== Remote changed (${current_url} -> ${HVISOR_REPO}), re-cloning ==="
                            fresh_clone
                        elif git -C "${HVISOR_SRC}" fetch --depth 1 origin "${HVISOR_BRANCH}" \
                            && git -C "${HVISOR_SRC}" checkout -f "${HVISOR_BRANCH}" \
                            && git -C "${HVISOR_SRC}" reset --hard "FETCH_HEAD"; then
                            echo "=== Updated hvisor at ${HVISOR_SRC} ==="
                        else
                            echo "=== Update failed, re-cloning ==="
                            fresh_clone
                        fi
                    else
                        fresh_clone
                    fi

                    test -f "${HVISOR_SRC}/jenkins/ci_runner.py"
                    echo "=== hvisor ready: ${HVISOR_SRC} ($(git -C "${HVISOR_SRC}" rev-parse --short HEAD)) ==="
                    '''
                }
            }
        }

        stage('Compile') {
            steps {
                dir("${env.HVISOR_SRC}") {
                    script {
                        def bid = parseBid(params.BID)
                        echo "Compile hvisor [BID=${params.BID}, ARCH=${bid.arch}, BOARD=${bid.board}]"
                        sh """
                            ${toolchainPathShell()}
                            chmod +x tools/kconfig/bootstrap_venv.sh tools/kconfig/host_config.sh tools/kconfig/save_defconfig.sh 2>/dev/null || true
                            if [ ! -x tools/kconfig/.venv/bin/python ]; then
                                ./tools/kconfig/bootstrap_venv.sh
                            fi
                            make defconfig ARCH=${bid.arch} BOARD=${bid.board}
                        """
                        if (bid.arch != 'x86_64') {
                            sh """
                                ${toolchainPathShell()}
                                make dtb ARCH=${bid.arch} BOARD=${bid.board}
                            """
                        }
                        sh """
                            ${toolchainPathShell()}
                            make all ARCH=${bid.arch} BOARD=${bid.board} MODE=release
                        """
                    }
                }
            }
        }

        stage('Build hvisor-tool') {
            steps {
                dir("${env.HVISOR_SRC}") {
                    script {
                        def bid = parseBid(params.BID)
                        sh """
                            set -eu
                            ${toolchainPathShell()}
                            json=\$(python3 '${env.WORKSPACE}/bid_config.py' --bid '${params.BID}' --hvisor-src '${env.HVISOR_SRC}')
                            KDIR=\$(echo "\${json}" | python3 -c "import sys,json; print(json.load(sys.stdin)['KDIR'])")
                            TARCH=\$(echo "\${json}" | python3 -c "import sys,json; print(json.load(sys.stdin)['TARCH'])")
                            if [ -z "\${KDIR}" ]; then
                                echo "ERROR: KDIR missing for BID=${params.BID}"
                                exit 1
                            fi
                            echo "Build hvisor-tool [BID=${params.BID}, TARCH=\${TARCH}, KDIR=\${KDIR}]"
                            if [ ! -d '${env.HVISOR_TOOL_PATH}/.git' ]; then
                                mkdir -p '${env.HVISOR_TOOL_PATH}'
                                git clone --depth 1 '${env.HVISOR_TOOL_URL}' '${env.HVISOR_TOOL_PATH}'
                            fi
                            make -C '${env.HVISOR_TOOL_PATH}' all ARCH="\${TARCH}" KDIR="\${KDIR}"
                        """
                    }
                }
            }
        }

        stage('Prepare test') {
            steps {
                dir("${env.HVISOR_SRC}") {
                    script {
                        def bid = parseBid(params.BID)
                        sh """
                            set -eu
                            json=\$(python3 '${env.WORKSPACE}/bid_config.py' --bid '${params.BID}' --hvisor-src '${env.HVISOR_SRC}')
                            KDIR=\$(echo "\${json}" | python3 -c "import sys,json; print(json.load(sys.stdin)['KDIR'])")
                            MODE=\$(echo "\${json}" | python3 -c "import sys,json; print(json.load(sys.stdin)['mode'])")
                            if [ -z "\${KDIR}" ] || [ -z "\${MODE}" ]; then
                                echo "ERROR: BID=${params.BID}: mode and KDIR are required"
                                exit 1
                            fi
                            if [ "\${MODE}" != "qemu" ]; then
                                echo "ERROR: ptest job only supports mode=qemu (got \${MODE})"
                                exit 1
                            fi
                            external='${env.TEST_IMG_BASE}/${bid.arch}/${bid.board}'
                            configure='./platform/${bid.arch}/${bid.board}/'
                            echo "Prepare rootfs [BID=${params.BID}] from \${external}"
                            cp -r "\${external}/." "\${configure}"
                            chmod +x jenkins/prepare.sh
                            sudo -E env \\
                                ARCH='${bid.arch}' \\
                                BOARD='${bid.board}' \\
                                KDIR="\${KDIR}" \\
                                WORKSPACE_ROOT="\$(pwd)" \\
                                HVISOR_TOOL_PATH='${env.HVISOR_TOOL_PATH}' \\
                                jenkins/prepare.sh
                        """
                    }
                }
            }
        }

        stage('Run ptests') {
            steps {
                sh """
                    export TERM=\${TERM:-xterm}
                    ${toolchainPathShell()}
                    ${qemuPathShell()}
                    python3 ptest_runner.py \\
                        --bid '${params.BID}' \\
                        --ptests '${env.SELECTED_PTESTS}' \\
                        --workspace '${env.HVISOR_SRC}'
                """
            }
        }

        stage('Archive results') {
            steps {
                script {
                    sh """
                        export HVISOR_SRC='${env.HVISOR_SRC}'
                        BID='${params.BID}'
                        ARCH=\$(echo "\${BID}" | cut -d/ -f1)
                        BOARD=\$(echo "\${BID}" | cut -d/ -f2)
                        REPO_ROOT='${env.WORKSPACE}'
                        ART_SLUG=\$(echo "\${BID}" | sed 's|/|__|g')
                        ART_DIR="\${REPO_ROOT}/artifacts/\${ART_SLUG}"
                        mkdir -p "\${ART_DIR}"
                        ROOTFS_EXT4="\${HVISOR_SRC}/platform/\${ARCH}/\${BOARD}/image/virtdisk/rootfs1.ext4"
                        MNT="\${HVISOR_SRC}/platform/\${ARCH}/\${BOARD}/image/virtdisk/rootfs"
                        case "\${BID}" in
                            aarch64/qemu-gicv3) HOME_SUB=arm64 ;;
                            riscv64/qemu-plic) HOME_SUB=riscv64 ;;
                            *) HOME_SUB= ;;
                        esac
                        if [ -f "\${ROOTFS_EXT4}" ] && [ -n "\${HOME_SUB}" ]; then
                            sudo mkdir -p "\${MNT}"
                            if sudo mount -t ext4 "\${ROOTFS_EXT4}" "\${MNT}" 2>/dev/null; then
                                if [ -d "\${MNT}/home/\${HOME_SUB}/test/perfresult" ]; then
                                    sudo cp -a "\${MNT}/home/\${HOME_SUB}/test/perfresult/." "\${ART_DIR}/" || true
                                    sudo chown -R \$(id -u):\$(id -g) "\${ART_DIR}" || true
                                fi
                                sudo umount "\${MNT}" || true
                            fi
                        fi
                    """
                    def artGlob = "artifacts/${params.BID.replace('/', '__')}/**"
                    if (fileExists('artifacts')) {
                        archiveArtifacts artifacts: artGlob, allowEmptyArchive: true, fingerprint: true
                    }
                }
            }
        }
    }

    post {
        always {
            script {
                sh """
                    if [ -f '${env.HVISOR_SRC}/.qemu/qemu.pid' ]; then
                        pid=\$(cat '${env.HVISOR_SRC}/.qemu/qemu.pid' 2>/dev/null || true)
                        if [ -n "\${pid}" ] && kill -0 "\${pid}" 2>/dev/null; then
                            kill -TERM "-\${pid}" 2>/dev/null || kill "\${pid}" 2>/dev/null || true
                        fi
                        rm -f '${env.HVISOR_SRC}/.qemu/qemu.pid'
                    fi
                """
            }
            echo "Build finished: ${currentBuild.currentResult}"
        }
    }
}
