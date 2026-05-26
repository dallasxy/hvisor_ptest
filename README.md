# hvisor_new_test

独立 Jenkins 编排仓库，用于在 Jenkins 网页上多选并运行 hvisor 性能基准测试（ptest）。

运行时从 GitHub 克隆 [hvisor](https://github.com/dallasxy/hvisor) 的 `config_refactor` 分支，通过 **`make ci-run` + UNIX socket** 启动 QEMU（与 hvisor 主仓库新版 Jenkins CI 一致），**不使用** expect + `make run` 旧方式。

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
- Python 3 + `pyserial`（`ci_config.py` 仅使用标准库，无需 PyYAML）

```bash
pip3 install pyserial
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
# 需先 clone hvisor 到 hvisor-src/
git clone --depth 1 --branch config_refactor https://github.com/dallasxy/hvisor.git hvisor-src

./scripts/run_ptests.sh \
  --bid aarch64/qemu-gicv3 \
  --ptests irq,mem \
  --hvisor-src ./hvisor-src
```

单独运行一个 ptest（需已构建 hvisor 并准备好 perf 镜像）：

```bash
python3 ptest_runner.py \
  --bid aarch64/qemu-gicv3 \
  --ptest irq \
  --workspace ./hvisor-src
```

## 执行流程

1. **Validate**：解析 Jenkins 参数（PTESTS / BID / …）
2. **Clone hvisor**：拉取 hvisor 到 `hvisor-src/`（含 `jenkins/ci_runner.py`）
3. **Build and prepare**：`make all`、hvisor-tool、`perf-prepare-img`
4. **Run ptests**：
   - 调用 hvisor 的 `jenkins/ci_runner.py` 中 **`zone0_start`**（`make ci-run` + qemu.sock）
   - zone0 就绪后，在同一 QEMU 会话中运行所选 benchmark（mem/irq/net/blk）
5. 从 rootfs 提取 `perfresult/` 到 `artifacts/` 归档

## 与 hvisor jenkins 的关系

- **zone0 启动**：复用 [`hvisor/jenkins/ci_runner.py`](https://github.com/syswonder/hvisor/blob/main/jenkins/ci_runner.py) 的 `zone0_start`（与主 CI 一致）
- **benchmark 执行**：`hvisor_new_test/ptest_runner.py` 在 zone0 进入 shell 后运行 `bench_*.sh`
- 不再使用本地 `terminal.py` 重复实现 boot 逻辑（仍保留文件作参考，运行时 import hvisor jenkins 模块）

## 与 hvisor 主仓库的关系

本仓库**完全独立**，不修改 hvisor 源码。仅运行时 clone hvisor 并在其 tree 内执行 make 命令。

| | hvisor 主 Jenkins | hvisor_new_test |
|--|-------------------|-----------------|
| 测试 | zone0/zone1 系统测试 | ptest 性能基准 |
| QEMU | `make ci-run` + socket | 相同 |
| 触发 | PR / push | Jenkins 手动参数化 |

## 配置来源

与 hvisor 主 Jenkins CI **完全一致**，clone 后使用：

- `hvisor-src/jenkins/ci.yaml` — KDIR、测试平台配置
- `hvisor-src/jenkins/ci_config.py` — 读取 ci.yaml
- `hvisor-src/jenkins/ci_runner.py` — `zone0_start`（`make ci-run`）

`hvisor_new_test/ci.yaml` 仅为本地参考，**运行时不再使用**。

## 配置修改

- 工具链 / QEMU / TEST_IMG 路径：编辑 `Jenkinsfile` 的 `environment` 块（与主 CI 相同）
- 内核路径 `KDIR`：修改 clone 下来的 `hvisor-src/jenkins/ci.yaml`
