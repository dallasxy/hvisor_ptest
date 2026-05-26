# hvisor_new_test

独立 Jenkins 编排仓库，用于在 Jenkins 网页上多选并运行 hvisor 性能基准测试（ptest）。

运行时从 GitHub 克隆 [hvisor](https://github.com/syswonder/hvisor)，通过 **`make ci-run` + UNIX socket** 启动 QEMU（与 hvisor 主仓库新版 Jenkins CI 一致），**不使用** expect + `make run` 旧方式。

## 支持的测试

| ptest | 说明 |
|-------|------|
| `irq` | 中断延迟基准 |
| `net` | 网络基准 |
| `mem` | 内存基准 |
| `blk` | Virtio-BLK 基准（zone1） |

支持平台：

- `aarch64/qemu-gicv3`
- `riscv64/qemu-plic`

## 目录结构

```
├── Jenkinsfile          # 参数化 Pipeline
├── ci.yaml              # BID / KDIR 配置
├── ptest_runner.py      # ci-run + qemu.sock 驱动 ptest
├── terminal.py          # QEMU socket 终端封装
├── ci_config.py         # 读取 ci.yaml
└── scripts/
    └── run_ptests.sh    # 克隆 hvisor、构建、调用 ptest_runner
```

## 依赖

### Jenkins 插件

- [Active Choices](https://plugins.jenkins.io/uno-choice/)（uno-choice v2）— 网页 checkbox 多选 `PTESTS`
- 首次运行若提示 **Script Security**，在 **Manage Jenkins → Script Approval** 中批准 `return ["irq", "net", "mem", "blk"]` 脚本

### Jenkins Agent

与 hvisor 主仓库 Jenkins 相同的环境：

- Rust / cargo
- QEMU（路径见 `Jenkinsfile` 中 `QEMU_PATH`）
- 交叉工具链（RISC-V、AArch64）
- Linux 内核源码（`ci.yaml` 中 `KDIR`）
- Python 3 + `pyyaml` + `pyserial`

```bash
pip3 install pyyaml pyserial
```

## 初始化新 Git 仓库

将本目录作为独立仓库根目录 push 到 GitHub：

```bash
cd hvisor_new_test
git init
git add .
git commit -m "Initial hvisor ptest Jenkins orchestration"
git remote add origin git@github.com:YOUR_ORG/hvisor-ptest.git
git push -u origin main
```

## Jenkins Job 配置

1. **New Item** → Pipeline → 名称如 `hvisor-ptest`
2. **Pipeline** → Definition: *Pipeline script from SCM*
3. SCM: Git，Repository URL 指向新仓库
4. Script Path: `Jenkinsfile`
5. 保存后点击 **Build with Parameters**
6. 在网页 **PTESTS** 复选框中勾选 irq / net / mem / blk（Active Choices `PT_CHECKBOX`）
7. 选择 `BID`，首次运行保持 `PREPARE_IMAGE` 勾选

## 本地调试

```bash
export CARGO_HOME=/usr/local/cargo
export QEMU_PATH=/path/to/qemu/build
export TOOLCHAIN_PATHS=/path/to/riscv/bin:/path/to/aarch64/bin
export WORKSPACE=$(pwd)

pip3 install pyyaml pyserial

./scripts/run_ptests.sh \
  --bid aarch64/qemu-gicv3 \
  --ptests irq,mem \
  --branch main
```

单独运行一个 ptest（需已构建 hvisor 并准备好 perf 镜像）：

```bash
python3 ptest_runner.py \
  --bid aarch64/qemu-gicv3 \
  --ptest irq \
  --workspace ./hvisor-src
```

## 执行流程

1. `run_ptests.sh` 克隆/更新 hvisor 到 `hvisor-src/`
2. `make all` + 编译 hvisor-tool
3. `make perf-prepare-img`（可选，首次必选）
4. 对每个所选 ptest 调用 `ptest_runner.py`：
   - `make ci-run` 启动 QEMU，串口绑定 `.qemu/qemu.sock`
   - Python `Terminal` 通过 socket 完成 boot 与 benchmark
5. 从 rootfs 镜像提取 `perfresult/` 到 `artifacts/` 供 Jenkins 归档

## 与 hvisor 主仓库的关系

本仓库**完全独立**，不修改 hvisor 源码。仅运行时 clone hvisor 并在其 tree 内执行 make 命令。

| | hvisor 主 Jenkins | hvisor_new_test |
|--|-------------------|-----------------|
| 测试 | zone0/zone1 系统测试 | ptest 性能基准 |
| QEMU | `make ci-run` + socket | 相同 |
| 触发 | PR / push | Jenkins 手动参数化 |

## 配置修改

- 工具链 / QEMU 路径：编辑 `Jenkinsfile` 的 `environment` 块
- 内核路径 `KDIR`：编辑 `ci.yaml`
