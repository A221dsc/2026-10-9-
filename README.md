# Adaptive PoolHBI

有序滑动窗口索引的成本感知 LIST/TREE 表示管理，以及同布局比较工程。源码版本由本仓库的 Git 提交与阶段标签管理。

## 当前阶段

S0 同布局合约已冻结；S1 匹配内核和驱动已通过独立规格及质量审查。统计、选择和入口模块已完成实际 RED 与 GREEN，正在独立审查。当前是工程候选版本，尚未批准开发选择、A/A 或正式性能实验。

- 固定 R6：epoch=512，min_tree_size=128，PAYBACK=2，K=32，d=4，C=8；成本表保持冻结值。
- 比较臂：Original、M_LIST、M_OBSERVE_LIST、M_EVENT、M_FIXED、R6、M_NO_IDLE。
- 所有开发门槛选择均使用独立 dev 输入；目前真实 selected_theta / selected_h 为空。
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

数据集、LLVM/Python 运行时、编译程序和完整运行归档保存在本地，并被 Git 忽略。工程全套验证需要本地已有的冻结依赖与归档记录；仅克隆源码不能冒认这些记录已执行或环境已验收。

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

