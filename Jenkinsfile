/** Active Choices Plugin v2 (uno-choice): PT_CHECKBOX multi-select for ptests. */
def normalizePtests(raw) {
    if (raw == null) {
        return []
    }
    if (raw instanceof List || raw.getClass().isArray()) {
        return raw.collect { it.toString().trim() }.findAll { it }
    }
    return raw.toString().split(',').collect { it.toString().trim() }.findAll { it }
}

properties([
    parameters([
        [
            $class: 'ChoiceParameter',
            choiceType: 'PT_CHECKBOX',
            description: 'Select one or more ptest benchmarks (Active Choices)',
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
                    def selected = normalizePtests(params.PTESTS)
                    if (selected.isEmpty()) {
                        error('PTESTS is empty: select at least one benchmark (irq/net/mem/blk)')
                    }
                    def valid = ['irq', 'net', 'mem', 'blk'] as Set
                    def bad = selected.findAll { !valid.contains(it) }
                    if (!bad.isEmpty()) {
                        error("Invalid ptest(s): ${bad.join(', ')}; use irq|net|mem|blk")
                    }
                    env.SELECTED_PTESTS = selected.join(',')
                    echo "BID=${params.BID} PTESTS=${env.SELECTED_PTESTS} BRANCH=${params.HVISOR_BRANCH}"
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
                            --ptests '${env.SELECTED_PTESTS}' \\
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
