# Adaptive PoolHBI

有序滑动窗口索引的成本感知 LIST/TREE 表示管理，以及同布局比较工程。源码版本由本仓库的 Git 提交与阶段标签管理。

## 当前阶段

S0 同布局合约已冻结。S1 工程标签为 `s1-engineering-v1`，源码提交为 `b9f5bd9`；三个 chunk 的独立规格与质量审查、全工程代码审查全部 Approved。根最终复核77项测试／44个进程及外层均exit0；内核99项检查、300万随机操作，驱动35套件／78个命令已验收。先前超时与失败完整保留。

DEV已完成：执行提交 `923c312`，30份开发输入、240个完整配对格子、960个DEV计时子进程和前后160个A/A子进程全部通过生产闸门。一次性选定 `theta=16`、`h=2048`。`DEV_READY=true`、`FINAL_READY=false`，同布局正式矩阵尚未运行。详见 [DEV实验报告](投稿准备/后续研究_20261008/S1/DEV_实验报告.md) 与 [入口清单](投稿准备/后续研究_20261008/S1/工程入口清单.md)。

- 固定 R6：epoch=512，min_tree_size=128，PAYBACK=2，K=32，d=4，C=8；成本表保持冻结值。
- 比较臂：Original、M_LIST、M_OBSERVE_LIST、M_EVENT、M_FIXED、R6、M_NO_IDLE。
- 所有开发门槛选择均使用独立dev输入；`selected_theta=16`、`selected_h=2048`已一次性冻结。不能用开发集收益宣称R6正式加速。
- 保留失败尝试及负结果；预制测试数据标记为 fixture，不能作为性能证据。

## 目录

| 路径 | 内容 |
|---|---|
| `投稿准备/后续研究_20261008/S0` | 同布局合约、预注册、覆盖矩阵和历史冻结审查 |
| `投稿准备/后续研究_20261008/S1/src` | 匹配内核、原生与诊断驱动 |
| `投稿准备/后续研究_20261008/S1/tests` | 正式正确性与预制统计/侧车测试 |
| `投稿准备/后续研究_20261008/S1/tools` | 工程构建、统计、选择、入口及静态命令适配 |
| `投稿准备/adaptive_poolhbi/final` | 保持不变的 R6 与共享类型/分配器 |
| `投稿准备/adaptive_poolhbi/final_experiments` | 冻结缓存和原始 PoolHBI 依赖 |
| `投稿准备/公开数据实验` | 固定核工具源码、原配对工具和数据准备脚本 |

三个已审查驱动的字节快照纳入 `S1/release/binaries`，由Git定位。DEV原始CSV、配对CSV、汇总及报告纳入本轮结果提交；全部输入、侧车与命令保存在本地不可覆盖的 `S1/artifacts/dev/DEV_20261010_01`。数据集、运行时、其他编译产物和完整运行归档由Git忽略。生产入口需要本地已有的冻结依赖及工程证据；仅克隆源码不能冒认环境已验收。

## DEV复现

使用协议登记的Python 3.12运行时，从仓库根运行：

```powershell
python -B 投稿准备/后续研究_20261008/S1/tools/dev_launch.py --output <new-absolute-run-directory>
```

启动器自动核对已冻结工程证据和程序，生成30份DEV输入与2份A/A输入，运行before A/A，通过起始闸门后直接串行执行240格，随后运行after A/A和一次性选择。每次使用新的空目录，保留实际失败，绝不按性能重跑或改参数。不会启动formal矩阵。

报告重建使用具备Matplotlib的Python：`tools/report_dev.py --run <absolute-run-directory>`。本轮报告使用已有Python 3.13／Matplotlib 3.10.8，只在计时结束后执行；首个绘图依赖失败原样保留，实验运行时未改。

## 工程验证

在已准备冻结依赖的 Windows 工作区，从仓库根目录运行。`python` 应指向协议登记的 Python 运行时；脚本会验收实际运行时身份。

```powershell
python -B 投稿准备/后续研究_20261008/S1/tools/check_kernel.py --tag kernel_new_attempt
python -B 投稿准备/后续研究_20261008/S1/tools/build_driver.py --tag driver_new_attempt
python -B 投稿准备/后续研究_20261008/S1/tools/run_engineering.py --tag analysis_new_attempt
```

每个 tag 创建不可覆盖的新尝试目录。最后一项仅执行预制正确性测试，不会启动性能矩阵。完整配对必须通过 raw、process、phase、receipt、config、cache 和环境共同验收；单个 GREEN 字样或单个合法 CSV 不足以放行。

## Git 版本规则

使用 `git log --oneline` 查看工程演进，使用阶段标签定位经审查的版本。工程候选和最终工程冻结分别记录；代码或协议变化产生新提交，并按受影响范围重新验证。

既有规范、数据和二进制一致性校验字段保留用于复现与验收；源码版本以 Git 提交为准。历史报告中的“不是 Git 仓库”描述属于引入 Git 前的执行环境。

