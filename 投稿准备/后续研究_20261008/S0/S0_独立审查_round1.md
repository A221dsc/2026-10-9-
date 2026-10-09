# S0 独立设计审查 · Round 1

Status: Issues Found/not freezable

审查日期：2026-10-08。裁决针对下方 SHA256 绑定的五份 S0 规范。审查对象是设计是否足以冻结并进入新增正式 RED 测试与实现规划；不要求 S0 存在实现、GREEN、trace 或 binary。

本轮只读规范与必要冻结源码，进行 JSON 解析、登记整数算术和 Get-FileHash。没有运行算法、正确性测试、校准、性能、A/A、机制、资源、延迟实验或编译；唯一新增文件为本报告。JSON 使用 PowerShell ConvertFrom-Json -AsHashtable，保留 n/N 的区分。未修改冻结 R6 或任何规范。

有两项明确阻塞，均可通过规格文字和机器字段修正，不需要改变 R6、成本值、负载、seed、候选阈值集合或计划样本量。除以下两项外，未发现阻止进入正式 RED 与实现规划的设计缺口。selected_theta/selected_h=null、NOT_RUN、新测试未写及两个 S1 gate=false 均是正确阶段状态，不是阻塞。

## Issues

### B01 — 原生四账统计的要求与冻结宏／编译口径不一致

精确位置：S0_同布局比较合约_v1.md 第 35 行（§3）；S0_实验预注册_v1.md 第 80 行（§5 编译要求）；S0_preregistration.json 的 environment.flags、environment.native_forbidden_macros（第 580–593 行）；S0_审计与范围裁决.md 第 14 行。

合约要求“原生模式保持冻结四类Alloc统计和内置转换计时的实际开销”，但四类 Alloc 的 current/peak/allocations/frees 更新受 final/shared_allocator.hpp 第 49–55 行的 INDEX_MEMORY 宏控制。pbadaptive::Alloc 是该 Alloc 的别名，见 adaptive_types.hpp 第 9–15 行。旧原生 unified_driver 的编译命令没有 INDEX_MEMORY，当前登记 flags 也没有该宏。因而存在两种不一致的可实现解释：按旧 native 关闭四账更新，或者为了满足合约字面要求在新 native 开启四账更新。后者会改变正式时间口径；前者又无法满足现有文字的统计承诺。此差异必须在性能之前裁定。

所需修法：

1. 将合约第 35 行改为明确三个模式的宏边界：native 和 latency 均不定义 INDEX_MEMORY；保留四账户对象、字段、分配上下文与内核布局，但这些模式的四账数值不可观测，导出 NA。保留原生 W/候选/转换等已经存在的内核计数和转换 Clock。resource 对全部匹配臂统一定义 INDEX_MEMORY，并另做独立 global owner 请求字节追踪；Original 无法对应的四账仍为 NA。
2. 在 JSON 增加或明确每模式宏设置；native forbidden 列表加入 INDEX_MEMORY 与实际失败注入宏 INDEX_FAILURE_TEST。现有 ALLOCATION_FAILURE_INJECTION 可保留，但它不是冻结 shared_allocator.hpp 的失败注入宏名。latency 同样关闭四账/global/failure 注入；resource 允许 INDEX_MEMORY 和 owner 追踪，禁止 failure 注入。
3. 同步预注册、审计文字及 SX15/SX19/SX24 对模式的要求。无需改 allocator 或 R6。未来 SX19/SX24 验收应检查实际预处理宏和编译命令，避免把四账字段存在误当原生四账计数开启。

### B02 — 确认性 CI 端点与判读阈值混用 log／比值尺度

精确位置：S0_实验预注册_v1.md 第 94、96、136 行（§6 与 §9）；S0_preregistration.json 的 statistics.ci、statistics.strong_fast、statistics.strong_slow（第 625、630–631 行）；S0_测试与指标覆盖矩阵.csv 的 SX21。

JSON 的 statistics.ci 明确定义 exp(mean_log ± t·sd_log/sqrt(10))，因此端点为正的“比值尺度”。strong_fast 却要求 CI_upper < 负的 log 阈值；若 CI_upper 指前述 CI，faster 永远不能成立。strong_slow 也会把正比值与接近零的 log 阈值比较。Markdown 第 94 行先 exp，第 96 行再称“区间 upper/lower”而未说明使用 exp 前端点，具有同样歧义。当前数值思想可成立，问题是接口和字段未明确尺度，会导出不同统计实现。

所需修法：令 x_i=log(two_round_ratio_i)，并显式登记：

- log_ci_lower = mean_log − t_(9,1−0.05/(2×42))·sample_sd_log/sqrt(10)。
- log_ci_upper = mean_log + 同一半宽。
- ratio_ci_lower/ratio_ci_upper 分别为 exp(log_ci_lower)/exp(log_ci_upper)，用于 geometric-mean ratio 的区间报告。
- faster：所有 x_i 及 log_ci_upper 都小于 −max(component_AA_log_floor,−log(0.95))。
- slower：所有 x_i 及 log_ci_lower 都大于 max(component_AA_log_floor,log(1.05))。

在 JSON 判据中使用这些完整字段名；Markdown 第 96 行明确“log 区间端点”；group_summary.csv 明确保存 log_ci_lower/upper 与 ratio_ci_lower/upper，AA_floor 明确 log 尺度；SX21 增加预制数值表对这两种尺度及 faster/slower/unresolved 的对账要求。保持 42 项族、alpha、5%门槛和十输入规则原值，不需要新增实验。

## 完整性、覆盖与范围核查

|审查维度|裁决与依据|
|---|---|
|门控与信用单位|M_EVENT 对完成的 LIST 观察 W>0 计一 event，零 W 不增、空闲观察前 reset、TREE 不积累；M_FIXED 无成本门槛、按操作后 n 和编译期 h 判定；R6 ns gain 与 PAYBACK=2 不变。range 只能观察，结构触碰才登记。SX05–SX08 覆盖这些分支。|
|epoch、cooldown 与配额|结构操作成功才推进，miss 正常推进，range 不推进。每 512 结构 API 为 epoch；C=8、d=4、K=32、无抢占；普通降级在 promotion 前、cooldown 表清理在二者之间，候选重验后清表。与冻结 process_epoch/structural_done 相符。SX09–SX12 覆盖。|
|cleanup 与异常|空 TREE 即时 cleanup、不占 scheduled 名额、同 epoch 可多次、total=sched+cleanup。成功结构操作后的转换失败不回滚 epoch；demote 失败允许成功 pool grow 留下容量；range 输出失败不提交部分观察。这些条款与冻结源码相符，SX13/SX14 对应。|
|匹配与归因诚实性|4096 预分配桶、Node/Bucket/Adaptive/Index 布局、reserve、池增长/复用和 multiset 类型均被约束。M_LIST 关闭观察时仍保留原内容循环；Original 为部署参考。R6/M_EVENT 被准确表述为信用/资格/排名整体策略差异；观察、调度、转换等配对净差异不做可加的精确 CPU 分解。B01 修复后模式边界可执行。|
|内容与输入|完整 pair 内容语义、重复时间身份、半开查询、完整输出、计数窗口及 erase+insert 单元被登记。F04 不复用等长旧函数，段长与各段 q/c 明确；F07 一基秩和第 r+8 键的上界正确。SX02/SX03/SX16–SX18 覆盖。|
|seed 与选择隔离|90001–90003 dev、91001–91010 final、92001 AA、93001–93003 mechanism、94001–94002 random-test 互不交集；与审计声明的七份历史登记内整数 seed 无交集。公开三个有序 case 同 seed 的起点关联已披露。θ/h 只按 30 dev 输入等权 mean log total 选择，精确 tie 选小阈值，正式结果不得反向重选。|
|矩阵算术|30 dev inputs；960 dev 主 children；160 dev AA；560 primary pairs/2240 primary children；560 diagnostic children；360 final AA；合计 4280。42 项确认性族=3×7×2。F04 query=341+10922+341=11604，API=2×262144+11604=535892。机制 U=3×32768+2×16384=131072，18 回放；latency/resource 各 490。均一致。|
|统计解释|median/IQR/wins 与 geometric-mean ratio CI 区分，Student-t/Bonferroni 条件假设和 AA 有限包络限制被明示；无异常值删行、性能重跑或期中扩样。B02 是尺度命名阻塞，非样本量或统计目标变更要求。|
|轨迹和原始接口|APHTRC01 v1 Bundle/Step 字段可承载登记负载；U 表示总单元，无 query 的 period=U+1 满足旧 reader 的正 period 要求；F04 以 segments 为阶段依据。hash/count 与 S0EXP001 完整查询参考分开，native 不冒充精确逐 record 证明。raw_native、phase、events、latency、resource、pair/group summary 和 manifest 具有所需身份/模式/哈希/尝试字段；修复 B02 的 summary 端点命名即可。|
|执行和失败边界|S0 → RED/实现 → GREEN → S1_DEV_READY → dev_selection → S1_FINAL_READY 分开；hash/语义/规格/缺失重复/亲和失败停批，完整匹配 pair 才 resume，中断 pair 保留 invalid_attempt 并另完整重跑；性能负面或 unresolved 保留。旧 GREEN 不能替代新分支证据。|
|范围与 YAGNI|未向冻结 R6 引入衰减、裁剪、预测、抢占、TTL、后台 epoch、slot 平局排序、轻量替代内核或 force 转换。S2/S3 不在本轮；本审查不要求扩正式矩阵、不要求 S0 创建运行产物。|

种子核对范围限于审计列出的历史协议字段；未把扫描所有临时输出或历史 raw 当作唯一性证明。mechanism_protocol.json 与 observer_protocol.json 的名字含 seed 的字段中未提取到整数，不据此虚构未登记 seed。

## Recommendations (advisory)

### A01 — 记录最高固定阈值在 dev 中的实际角色

全部 dev 的每桶初始 n≤4096，并且 endpoint 或删后插回都保持每桶单元末 n，因此 h=8192 在这 30 个输入中始终不触发 promotion；它是带观察/管理的“不升级”极端候选。可在 dev_selection 的候选说明中加一句这一事实，并保留 SX07 对 n=8192 门槛的正式边界测试要求。此事实不使候选无效，也不要求改变候选集或增加校准格子。

### A02 — 来源清单区分当前辅助头与历史 build 记录

本轮 current driver_core.hpp 与 trace_cache.hpp 的 SHA 均不同于旧 driver_build.json 内 source map 的值。S0 合约已要求新 driver/binary 另哈希、另 A/A，所以这不是新增设计阻塞。资产清单应给当前字节及其既有冻结来源，保留历史 snapshot，避免把旧 driver_build.json 的整个 source map 称为当前逐文件一致；实际 Python runtime 与历史 runtime 的差异也应作为当前来源单列。不能据静态 hash 给当前实时拓扑、亲和性或新 binary 盖验收章。

## 审阅文件 SHA256

以下路径统一以 C:/Users/zhangjiacheng/Desktop/zjc/小论文/投稿准备/ 为基准；摘要为本轮直接 Get-FileHash -Algorithm SHA256 结果。规范冻结或修订后必须另保存新摘要并重审 B01/B02；本报告不能自动批准与这些摘要不同的后续字节。

### S0 规范

|文件|SHA256|
|---|---|
|后续研究_20261008/S0/S0_同布局比较合约_v1.md|53e4201ed476892f47c802244b8f56d3775f10dffe1aa1dcde3491e833b0d588|
|后续研究_20261008/S0/S0_实验预注册_v1.md|8a064ed19ca6d22b12f94a486241c416fdfd0b20d1ee14d9ed19d9b569882842|
|后续研究_20261008/S0/S0_preregistration.json|bda9c4a0d3f4725ac5622f02a7251bed3f8b6d24743ea6a797e4f044103d2eb9|
|后续研究_20261008/S0/S0_测试与指标覆盖矩阵.csv|bffcbb7489832a3f442549dd3ac333258cb4bfbb7841f894dcf44b340ae29fa7|
|后续研究_20261008/S0/S0_审计与范围裁决.md|5b9db6aadff713cca76f8083976eb0069f5466398f7ab6ea59b267cc490e78fe|

### 冻结源码及只读辅助依据

|文件|SHA256|
|---|---|
|adaptive_poolhbi/final/adaptive_poolhbi_final.hpp|8e7a351e8ee14a1a5511a99502f7d938296cc57c3757a74d7b45fc2071a63e0c|
|adaptive_poolhbi/final/frozen_config.hpp|5efb54ce732ede2b9b25f7ea39240fccb95bdc08462733f89d3363c0473f6074|
|adaptive_poolhbi/final/shared_allocator.hpp|66ad9ec278c27a07fcc8c63d00c303f46a48fe7ac4e26bdf801d7fca024c462f|
|adaptive_poolhbi/final/adaptive_types.hpp|5bf2baa9fab583e3342fd45485d3770ac4e2a71d0abd5a88e63e15d34e78cabe|
|adaptive_poolhbi/final_experiments/driver_core.hpp|91c332cb32a66b7195a0c28968eed7a9d703f5270e1ba72e8fa42868ae351c43|
|adaptive_poolhbi/final_experiments/trace_cache.hpp|95ab6a9a695081085f64e2944fff32de2d72efb8a4ebe2e6eb93c5ea15f609a7|
|adaptive_poolhbi/final_experiments/wall_driver.hpp|ca2bc88e7e891605d352531c0054c8f00d76b2e1ddef9940143bad275546aa03|
|adaptive_poolhbi/final_experiments/legacy/generators.hpp|954cc8e923911926f1a689ba3eac2afd30c71351b87220713a62659d9730d6a6|
|adaptive_poolhbi/final_experiments/legacy/pool_index.hpp|710202ee8396ac899d11cf3e3945ab5d630d8d86d3651cd7cec0da93bba45774|
|adaptive_poolhbi/final_experiments/method_adapters.hpp|fec115a3f03340028cc7efdedcaefaef6a26c59fc36d3c39faab35a544f6ce68|
|adaptive_poolhbi/final_experiments/driver_build.json|b700ca76b10102aa0252c00843734e007e9ca4ffe7eb4ab8c9daf5be41af9e44|
|adaptive_poolhbi/final_experiments/build_observer.py|798dbeeb11863387c57096620129ad0b1be351e628bdf72f72eca8444ffacc2e|

### 历史 seed 登记核对依据

|文件|SHA256|提取到的整数 seed|
|---|---|---|
|adaptive_poolhbi/final_experiments/protocol.json|c42f39fd495b2dcbcf3924503492b3ac16a9689322397af890508fb8e60c3800|71001–71005；72001–72005；73001–73005；74001–74005；75001–75005；76001–76003；78001|
|adaptive_poolhbi/final_experiments/mechanism_protocol.json|a8469481beb9cf72fc7f7cc3330c2b3fcbd1535fdcd822af59bf02daff1159af|无|
|adaptive_poolhbi/final_experiments/observer_protocol.json|49edbb2c7b2785737272dfef8083a85f6bd969dfc88091fd5738b75e867c8e86|无|
|adaptive_poolhbi/final_experiments/C_phase_observation_registration_v3.json|aab983eb75a0c5c79a5255802d94e0db17d7d7ea83ff56e2f813430becaa6ced|72001–72005|
|adaptive_poolhbi/supplementary_20261007/horizon/protocol.json|f51d20a3e793e930752fa4c994f763da7ba95f506f212d7d22959a2ca9e52271|81001–81005；81901|
|adaptive_poolhbi/supplementary_20261007/bucket/protocol_candidate.json|f68fa525c0dca30422da64aa2b748c8faf01c85697b99250ae6060f1c93f4558|82001–82005|
|adaptive_poolhbi/supplementary_20261007/bucket/aa_protocol_candidate.json|a07d9e79567030b9c24e65a26b8d3ae746d3fd059d0980a671559dfdf8e8cbf6|82001–82005|

