# hvisor_new_test

独立 Jenkins 编排仓库，用于在 Jenkins 网页上多选并运行 hvisor 性能基准测试（ptest）。

**启动流程与 hvisor 主仓库 Jenkins CI 一致**（Compile → hvisor-tool → `TEST_IMG_BASE` + `prepare.sh`）。本仓库通过 **Python import** 借用 hvisor `jenkins/` 里的函数（`zone0_start`、`build_terminal` 等），**不修改、不复制、不直接 subprocess 调用**外部 jenkins 脚本。

## 支持的测试

| ptest | 说明 |
|-------|------|
| `irq` | 中断延迟基准 |
| `net` | 网络基准 |
| `mem` | 内存基准 |
| `blk` | Virtio-BLK 基准（zone1） |

支持平台：`aarch64/qemu-gicv3`、`riscv64/qemu-plic`

## 目录结构

```
├── Jenkinsfile       # Pipeline（构建/准备同主 CI，测试调用本仓库脚本）
├── bid_config.py     # import ci_config 读取 KDIR（不调用 jenkins/ci_config.py CLI）
└── ptest_runner.py   # import zone0_start + 运行 bench_*.sh
```

## 执行流程

1. **Validate** — 解析 PTESTS / BID
2. **Clone hvisor** — 拉取 `hvisor-src/`
3. **Compile** — `defconfig` / `dtb` / `make all`（同主 CI）
4. **Build hvisor-tool** — `bid_config.py` 读 KDIR
5. **Prepare test** — `TEST_IMG_BASE` + `jenkins/prepare.sh`（同主 CI）
6. **Run ptests** — `ptest_runner.py`：import `zone0_start`；若选了 PTESTS 则跑 benchmark，否则仅启动 zone0 后退出
7. **Archive** — 提取 `perfresult/`

## 本地调试

```bash
git clone --depth 1 --branch config_refactor https://github.com/dallasxy/hvisor.git hvisor-src
# 按 Jenkinsfile 完成 compile / tool / prepare ...
python3 ptest_runner.py \
  --bid aarch64/qemu-gicv3 \
  --ptests irq,mem \
  --workspace ./hvisor-src
```

QEMU 已手动启动时：

```bash
python3 ptest_runner.py --bid ... --ptests irq --workspace ./hvisor-src --skip-zone0
```

## 与 hvisor 主 CI 的关系

| 阶段 | 实现方式 |
|------|----------|
| 构建 / 准备 | Jenkinsfile shell（同主 CI） |
| zone0 启动 | `ptest_runner` import `ci_runner.zone0_start` |
| benchmark | `ptest_runner` 本仓库逻辑 |
| 配置读取 | `bid_config` import `ci_config.get_bid_entry` |

不修改 hvisor 源码；clone 后仅在运行时 `sys.path` 引入 `hvisor-src/jenkins/`。
