properties([
    parameters([
        extendedChoice(
            defaultValue: 'irq',
            description: 'Select one or more ptest benchmarks (multi-select)',
            multiSelectDelimiter: ',',
            name: 'PTESTS',
            quoteValue: false,
            saveJSONParameterToFile: false,
            type: 'PT_MULTI_SELECT',
            value: 'irq,net,mem,blk',
            visibleItemCount: 4,
        ),
        choice(
            name: 'BID',
            choices: ['aarch64/qemu-gicv3', 'riscv64/qemu-plic'],
            description: 'Target platform (ARCH/BOARD)',
        ),
        string(
            name: 'HVISOR_REPO',
            defaultValue: 'https://github.com/syswonder/hvisor.git',
            description: 'hvisor Git repository URL',
        ),
        string(
            name: 'HVISOR_BRANCH',
            defaultValue: 'main',
            description: 'hvisor branch or tag to clone',
        ),
        booleanParam(
            name: 'PREPARE_IMAGE',
            defaultValue: true,
            description: 'Run make perf-prepare-img before ptests (recommended on first run)',
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
        HVISOR_TOOL_URL = 'https://github.com/syswonder/hvisor-tool.git'
        HVISOR_TOOL_PATH = 'hvisor-tool'
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
                    def selected = (params.PTESTS ?: '').split(',').collect { it.trim() }.findAll { it }
                    if (selected.isEmpty()) {
                        error('PTESTS is empty: select at least one benchmark')
                    }
                    def valid = ['irq', 'net', 'mem', 'blk'] as Set
                    def bad = selected.findAll { !valid.contains(it) }
                    if (!bad.isEmpty()) {
                        error("Invalid ptest(s): ${bad.join(', ')}; use irq|net|mem|blk")
                    }
                    echo "BID=${params.BID} PTESTS=${selected.join(',')} BRANCH=${params.HVISOR_BRANCH}"
                }
            }
        }

        stage('Run ptests') {
            steps {
                script {
                    def prepareFlag = params.PREPARE_IMAGE ? '' : '--no-prepare-image'
                    sh """
                        export TERM=\${TERM:-xterm}
                        export HVISOR_REPO='${params.HVISOR_REPO}'
                        export HVISOR_BRANCH='${params.HVISOR_BRANCH}'
                        export HVISOR_SRC='${env.WORKSPACE}/hvisor-src'
                        export HVISOR_TOOL_URL='${env.HVISOR_TOOL_URL}'
                        export HVISOR_TOOL_PATH='${env.HVISOR_TOOL_PATH}'
                        export CARGO_HOME='${env.CARGO_HOME}'
                        export QEMU_PATH='${env.QEMU_PATH}'
                        export TOOLCHAIN_PATHS='${env.TOOLCHAIN_PATHS}'
                        chmod +x scripts/run_ptests.sh
                        ./scripts/run_ptests.sh \\
                            --bid '${params.BID}' \\
                            --ptests '${params.PTESTS}' \\
                            --repo '${params.HVISOR_REPO}' \\
                            --branch '${params.HVISOR_BRANCH}' \\
                            --hvisor-src '${env.WORKSPACE}/hvisor-src' \\
                            ${prepareFlag}
                    """
                }
            }
        }

        stage('Archive results') {
            steps {
                script {
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
            echo "Build finished: ${currentBuild.currentResult}"
        }
    }
}
