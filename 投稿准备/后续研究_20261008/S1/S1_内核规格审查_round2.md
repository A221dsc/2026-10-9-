# S1 内核独立规格复审（Chunk 1，round 2）

日期：2026-10-09。**Verdict：Approved，MF1–MF3 已关闭，无剩余阻断项。** 本裁决仅批准 Chunk1 的 SX01–SX15 规格实现与正确性证据，可进入计划要求的 quality 审查；不表示后续驱动/统计/入口已完成或任何实验入口 READY。

本轮只复审首轮三个缺口与补测产生的新完整 GREEN。首轮报告 [S1_内核规格审查.md](C:/Users/zhangjiacheng/Desktop/zjc/小论文/投稿准备/后续研究_20261008/S1/S1_内核规格审查.md) 保留，实际 SHA 仍为 `c4a14fdce9033ec71581fc884a798fabfd6fcdb9dce80353a342ef746d8044e9`，其 NOT APPROVED 对应旧测试快照而非本轮修订。

## 固定审查 basis

- 新受审测试快照：`artifacts/kernel/green_coverage_fix_01/source/tests/test_kernel.cpp`，SHA256 `75748ba98b15e6a000ebac5a03838a11f6d20c2fe1de1fcbb571b0fc685a1bb2`。
- 新完整 GREEN：`artifacts/kernel/green_coverage_fix_01/manifest.json`，SHA256 `afaa291739db2b9512cb780d7786d232bee4a41cef6e4c18ab21461c053ced8c`。
- 新行为 RED：`artifacts/kernel/red_coverage_fix/manifest.json`，SHA256 `f7dfffa8847e4a8344bfc7b017779a2c18f456b1719c39ea28451e326fa4c589`。
- 匹配内核 SHA 不变：`dbbcdad499564408574d284594ca6e253d3af8215e80f04b9260b7dcb575ba08`；诊断副本 SHA 不变：`518dfcd5a0fcfe1b85564d892efbfac75f81b94de3b5f27ad9238ddcb20d0080`。

本轮测试行号全部绑定上述新快照；当前测试与该快照逐字节 SHA 相同。所有路径属于 `C:/Users/zhangjiacheng/Desktop/zjc/小论文/投稿准备/后续研究_20261008/S1/`。本轮没有修改 src/tests、S0 或旧文件，没有运行性能、调参、校准、A/A 或正式机制矩阵，也没有重复执行大规模正确性 suite；结论来自实际代码、归档命令、逐例 process/stdout/stderr、独立哈希与日志重放。

## 三项修复的独立裁决

| 首轮缺口 | 本轮实际实现与执行证据 | 裁决 |
|---|---|---|
| MF1 / SX02 全部7臂需直接 R6 | 新快照 L28–33 的 `FrozenR6Adapter` 直接继承冻结 `pbadaptive::Index`，仅有继承构造及 static constexpr arm，没有字段或重写内容 API，并用 sizeof 断言无增量。L154–158 对该 adapter 调用与新匹配臂相同的 `contents()`；L68–98 是完整参考 multiset/重复键/erase/miss/invalid/range/build 用例。六模式日志都有 `SX02 direct_frozen_R6_complete_contents PASS`，且整个 SX02 最终 PASS、exit0。 | Closed |
| MF2 / SX09 逐 API 转换统计 | L272–331 新增外部 `ApiAudit`，每个实际 range/erase 前后核对 epoch、ops、promotion、scheduled、cleanup、total、tree count、K32；检查 `total=scheduled+cleanup`、增量归属、非结构 clock 不推进、转换只在结构边界、每个 epoch 最多1升1scheduled。L332–365 使 budget 与 cleanup 两个 fixture 全部 API 经过该 audit，转换 API 写逐笔日志；L352–355 又明确逐条最后 erase 的 cleanup+1，并验证两个 cleanup 都不占 scheduled 配额。六模式实际日志均可重放到 summary，详见下表。 | Closed |
| MF3 / SX11 NoIdle cleanup 后重新升树 | L384–409 使用合法 API：升树→推进 idle 到epoch9但保持 TREE/0scheduled→实际清空256记录 cleanup→重新插入256记录→C8内反复正 W range和合法结构触碰仍不得候选→到期 range仅观察→结构miss登记候选→epoch18再次升级。L410 将该 fixture 加入 SX11，再执行既有 Cost/Event/Fixed 测试。六模式日志均确认 cleanup_epoch9、cooldown_end17、reupgrade_epoch18、promotions2、cleanup1、scheduled0；完整内容等于原 v。 | Closed |

点击查看新受审测试：[test_kernel.cpp:28](C:/Users/zhangjiacheng/Desktop/zjc/小论文/投稿准备/后续研究_20261008/S1/artifacts/kernel/green_coverage_fix_01/source/tests/test_kernel.cpp:28)、[ApiAudit:274](C:/Users/zhangjiacheng/Desktop/zjc/小论文/投稿准备/后续研究_20261008/S1/artifacts/kernel/green_coverage_fix_01/source/tests/test_kernel.cpp:274)、[NoIdle fixture:384](C:/Users/zhangjiacheng/Desktop/zjc/小论文/投稿准备/后续研究_20261008/S1/artifacts/kernel/green_coverage_fix_01/source/tests/test_kernel.cpp:384)。

审查者比较首轮与新测试：变化仅在 `tests/test_kernel.cpp`。既有方法的内容、参数、调用顺序和 aggregate 断言没有删弱；SX09 的原操作被等价 audit wrapper 包装，新增逐 API 断言和日志；SX11 在既有 sx10() 之前新增 NoIdle fixture。其余七个受审源码/工具 SHA 与首轮相同，六模式编译 flags 也相同。

### SX09 实际日志的逐笔归属

六模式均独立保存相同数量的4臂×2 fixture审计记录。审查者解析实际 stdout，将所有转换 API 增量重新累加，核对每个 summary 的 promotion/scheduled/cleanup/total 与转换 API 数量；48个 fixture 重放均匹配。

| fixture | 臂 | checked APIs / conversion APIs | promotion / scheduled / cleanup / total down |
|---|---|---:|---|
| budget | Fixed、Event、Cost、NoIdle 各自 | 234696 / 32 | 32 / 0 / 0 / 0 |
| cleanup_quota | Fixed、Event、Cost 各自 | 6249 / 6 | 3 / 1 / 2 / 3 |
| cleanup_quota | NoIdle | 6249 / 5 | 3 / 0 / 2 / 2 |

cleanup_quota 中两个真实 cleanup 分别属于 API5865 和 API5993，均为 erase、epoch10→10，ops分别127→128和255→256。普通 scheduled demotion 属于 API6249 的实际 erase 周期边界，epoch10→11、ops511→0；NoIdle 没有该 scheduled 事件。三次 promotion 分属 API712、1425、2139 的周期边界。该逐笔对账不是正式 EventSink 或 latency/resource 事件驱动验收。

代表日志：[native_SX09.stdout.log](C:/Users/zhangjiacheng/Desktop/zjc/小论文/投稿准备/后续研究_20261008/S1/artifacts/kernel/green_coverage_fix_01/native_SX09.stdout.log)，SHA256 `8552215b1f0d73acc714c848b9b4c0cfbf26c2b32038b92f10be4335aef9e9da`。

## 新 RED 与完整 GREEN 核验

新 RED 在 native/debug/owner 三模式全部编译成功，三次 record-layout 进程退出0；36个用例8 PASS/28具体行为断言 FAIL，没有 COMPILE失败或SKIP。SX11 明确失败于 `SX11 NoIdle tree survives idle until actual cleanup`；R6负对照不会伪造 NoIdle idle保留行为。新 RED 的直接R6子用例 PASS 与随后匹配 LIST 特性 FAIL 能同时出现在 SX02 日志，本复审核对最终独立 case行与退出码，没有将子用例PASS误读成完整用例PASS。

本轮最终 GREEN manifest 已完整落盘，不是运行中快照。独立核验结果：

- 99个case全部PASS、exit0、无SKIP、每份stderr为空；模式分布 native21/debug13/owner12/diagnostic11/ASAN21/UBSAN21。
- 六次编译及六次record-layout进程均exit0、stderr为空；读取六份layout实际记录，Index均1160 B。Node/Adaptive/Bucket源码及首轮已审布局未变。
- native、ASAN、UBSAN各有5新臂×94001/94002×100000的完整矩阵；逐个stdout都确认seed、operations=100000、mismatches=0，共3000000随机操作。
- manifest所有complete_gate为true，not_run_ids为空；审查者另外逐例检查真实日志，不只接受gate自报值。
- 两次新attempt所有源码快照、当前源码、六个GREEN binary/三个RED binary实际SHA与对应manifest匹配。旧四源SHA与S0绑定及两attempt相同；实际编译器/Python文件SHA与S0绑定相同；S0资产manifest自身SHA也匹配。
- matched/diagnostic/kernel_codegen/derive/check/allocator/red adapter均未变；原27不变函数、成员布局及代表性codegen证明仍绑定同一内核。codegen证明仅用于关闭路径审查，不作性能结论。

代表新增日志 SHA：native SX02 `5f29c80f44bae55d48cce32ce9f0e08d6339651c923be174a610355fa7fcad6e`；native SX11 `98b90eff97a9b410373373f40dc92dd1e0621eb1d0237b1a2ad7e11b91361968`。

## 继续保留的非阻断边界

首轮已声明的范围仍成立：SX03小规模随机集合最多96条，不含随机转换压力，转换由另行合法fixture验证；SX08仍是3候选tie/33桶budget，未穷举4096候选压力；R6/Cost无tie对账是短单桶轨迹；故障前缀不是全可达失败点穷举。MF1–MF3的补测没有把这些边界改写为完整穷举证明。

owner正确性构建不是正式resource驱动READY。后续Chunk2仍需验证事件sink的ordinal/type/slot/n/latency、采样与完整native/latency/resource宏表，正式导出M_LIST work与native/latency四账NA以及Event信用单位。当前批准不包含上述后续工作。

**最终裁决：Approved（Chunk1规格复审）。三项首轮阻断已由新正式执行证据关闭，受审实现与冻结边界未变。**
