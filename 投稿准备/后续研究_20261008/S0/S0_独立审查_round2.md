# S0 独立设计复审 · Round 2

Status: Approved/freezable

审查日期：2026-10-09。批准范围为下方 SHA256 绑定的当前五份 S0 规范：设计完整、内部一致，边界清楚，可进入新增正式 RED 测试与实现规划。此裁决不是新增实现 GREEN、校准入口 READY 或正式性能入口 READY。

本轮重新审阅五份当前规范、入口清单及静态核验脚本；将 JSON 与 audit/round1_input 的第一轮 JSON 逐顶层字段对比；只读复核必要源码宏和当前来源哈希。JSON 使用 PowerShell ConvertFrom-Json -AsHashtable，未合并 n/N。没有运行 S0_静态核验.ps1、算法、编译器、测试、校准、A/A、拓扑探针或任何实验。唯一新增文件为本复审报告，未改规范或旧源。

## Issues

无未解决 blocker。第一轮 B01、B02 均已清除。

### B01：已解决 — 三个测量模式的分配统计口径明确一致

合约 §3 第 35、37 行，预注册 §5 第 80 行，JSON environment.native_forbidden_macros/mode_macros，审计第 14 行及 SX15/SX19/SX24 现在一致：

- native 与 latency 不定义 INDEX_MEMORY，保留四账户对象、字段和分配上下文，四账数值不可观测，导出 NA；R6 已有 work/候选/节点/转换计数及内置转换 Clock 保留。
- resource 对所有匹配臂统一开启 INDEX_MEMORY、ADAPTIVE_ALLOC_TRACK，并在另名观察副本开启 S0_EVENT_TRACE。Original 无法对应的四账为 NA，whole 请求空间仍由独立 owner 追踪。
- INDEX_FAILURE_TEST 在三个测量模式均禁止。native 排除诊断事件、global 追踪和 ADAPTIVE_ABLATION；latency 排除四账/global 追踪和 ablation，仅观察副本开启事件接口；resource 也不启用 ablation。
- 实际宏表、编译命令纳入未来入口验收；失败注入只属于单独的正确性构建，不进入测量模式。

这些要求与冻结 shared_allocator.hpp 的 INDEX_MEMORY/INDEX_FAILURE_TEST 条件编译一致，不需要改变 allocator、R6 或其生产布局。SX15/SX19/SX24 已有相应验证需求，原先两种不同 native 解释已被消除。

### B02：已解决 — log 判读与 ratio 区间报告分开

预注册 §6 第 96、98 行、§9 第 138 行，JSON statistics 及 SX21 已同步指定：

- log_ci_lower/upper 为 mean_log 加减条件 Student-t 半宽。
- ratio_ci_lower/upper = exp(log_ci_lower/upper)，报告 geometric-mean paired ratio 的区间。
- faster 只比较全部十个 x_i 和 log_ci_upper 与负的 log 效应/噪声阈值；slower 只比较全部十个 x_i 和 log_ci_lower 与正的 log 阈值；AA 地板为 component_AA_log_floor。
- group_summary 保存两种尺度端点，SX21 要求预制 CSV 对尺度和三种判读结果做数值对账。

42 项确认性族、family alpha=0.05、df=9、十输入、5%关注效应均保持。median/IQR 与 geometric-mean CI 的区分及条件假设仍清楚；没有引入新的统计目标或样本。

## 完整性与范围复核

|项目|复审结论|
|---|---|
|R6 冻结与匹配|必要 R6/配置/分配器/驱动/缓存/生成器/Original 源码 SHA 与第一轮一致。没有衰减、裁剪、预测、抢占、TTL、后台 epoch、force 或 slot 平局规则变更。新 M_ 内核、生产 R6 和诊断副本的边界保持。|
|门控／信用／epoch／cooldown|M_EVENT 的 event 单位、M_FIXED 的操作后大小、R6 的 ns gain、范围不登记候选、结构 miss 正常推进、K32/d4/C8、每 epoch 一升一普通降级均保持。SX05–SX12 的覆盖没有削弱。|
|cleanup 与异常|cleanup 即时且不占普通额度；scheduled 与 cleanup 分账；成功结构操作后的转换失败不回滚 epoch；demote 失败允许已成功 pool grow 留存；range 输出失败不提交部分观察。SX09/SX13/SX14 保留。|
|归因与测量|同布局净差异、Original 部署参考、共享 W/范围缓冲的事件臂解释限制都明确；不加配对时间差充当精确成本分解。build/online/初终内容核验/destroy、native/latency/resource 的时间及资源边界一致。|
|输入与接口|F04 三个不等长阶段、F07 八条完整前缀输出、完整键/身份/半开区间、APHTRC01/Bundle/Step、无查询 period=U+1、S0EXP001 精确参考及 hash/count 的证明范围均保持。raw/summary/事件/资源接口已消除 CI 尺度歧义。|
|seed 与 dev 选择|登记 seed 集合不变；第一轮限定历史登记范围的分离结论仍适用。θ/h 仅在 30 dev 输入和固定候选中等权 mean-log total 选择，selected 仍为 null/NOT_RUN；正式种子只评估。|
|矩阵与统计数量|dev 960+dev AA 160+primary 2240+diagnostic 560+final AA 360=4280；primary pairs=560；确认性族=42；F04 query=11604、API=535892；机制 U=131072/18 回放；latency/resource 各490，均未改变。|
|覆盖、入口与失败|SX01–SX24 全部仍为 NOT_WRITTEN_NOT_RUN，新增 RED/GREEN 不能被旧证据顶替。S1_DEV_READY/S1_FINAL_READY=false；hash/内容/规格/环境失败停批与完整 pair resume 规则保留。负面性能与 unresolved 不删格或重跑补赢。|
|YAGNI 与可冻结边界|修正不扩正式或 dev 矩阵，不要求 S0 创建实现、binary、trace 或 GREEN；S2/S3 仍在范围外。当前规格足以指导正式 RED 与实现规划。|

JSON 与第一轮的顶层差异仅为 dev_selection、environment、statistics、diagnostics。diagnostics 新增机制 rng_tag=5 和 hot_phase_round_robin_reset=true，是将原正文已有规则显式机器登记，没有改变机制矩阵或负载。freeze、layout、methods、pairs、seeds、dataset、rng、synthetic、cases、timing、AA、planned_counts、execution、gate、interfaces、failure 均未变。

第一轮 advisory A01 已在正文和 JSON 说明 h=8192 的 dev 不升级极端候选角色，SX07 保留门槛边界覆盖；未增加有利格子。A02 已在审计与来源脚本区分当前辅助头、旧快照及当前/历史 Python runtime：driver_core.hpp 和 trace_cache.hpp 当前 SHA 直接匹配既有 horizon/manifest_start.json 的 frozen_assets。当前环境依旧要求 S1 实时验收，新 driver/binary 仍需另哈希、另 A/A。

## 静态入口记录的解释

只读检查既有 S0_核验记录.json：check_count=103、failed_count=6，即 97 项通过；失败恰为第一轮否决状态一项及五份已修正规范与第一轮输入 SHA 不一致。该记录的 FAIL 和 S0_SPEC_FREEZABLE=false 与复审前状态一致，不能表述为 103 项全部通过，也不等于新算法失败。

本报告提供当前规范的批准和哈希绑定。S0 整体冻结记录仍应由静态核验流程在本报告存在后重新生成并确认通过；本独立复审没有执行或预先宣称那个流程已通过。两个 S1 READY 继续为 false。

## Recommendations (advisory)

### A03：已处理 — 后续多轮审查按 round 数字排序

初次只读时脚本第 135 行按名称字典序，与入口清单第 20 行的数字最大 round 规则在未来 round10 时可能不一致；当时的 round1/round2 仍正确，故仅列 advisory。报告保存期间主代理只修元数据脚本，第 135 行现按去掉文件名前缀后的整数 round 排序。已只读复核该行以及新增复审前旧 review 拒绝记录绑定，当前脚本 SHA 见下表；五份规范 SHA 均未变。此建议已处理，没有剩余 advisory 验收条件，不增加算法、测试或实验范围。

## 当前审阅规范 SHA256

以下为本轮直接 Get-FileHash -Algorithm SHA256 的结果。批准只适用于这些字节，后续规范变更不得沿用本裁决。

基准目录：C:/Users/zhangjiacheng/Desktop/zjc/小论文/投稿准备/后续研究_20261008/S0/。

|规范文件|SHA256|
|---|---|
|S0_同布局比较合约_v1.md|c0a9a6bb805ff03c38c61c220b10526c5b7a5d0e9796ea82e2ed0d7c7ef0027c|
|S0_实验预注册_v1.md|860b923dba0db7933f2deacdff8539a2cc75b029058f5f06465a074854e09a08|
|S0_preregistration.json|bdb24556642d4137ab485befac9758b0abb04d933ebe5a3493b03d981cd9118a|
|S0_测试与指标覆盖矩阵.csv|92c7d6e72b7f0ba9726560418ae3fdda92b5602ca819e0906c2fbc4370c976fc|
|S0_审计与范围裁决.md|d1a27b81abc1606726019d6a41fd484268987a782a1c479ab0ffd3930f5b1c4a|
|S0_入口清单.md|d9f0586f3ee5892206d8dd61d07bdc9778f014377af1385e650de8909831d93d|
|S0_静态核验.ps1（只读审阅）|1df695ed1f211e09f41319e8d52cafeded623817341a575a6e585dfeef591c98|

### 冻结源码与来源复核 SHA256

基准目录：C:/Users/zhangjiacheng/Desktop/zjc/小论文/投稿准备/adaptive_poolhbi/。

|文件|SHA256|
|---|---|
|final/adaptive_poolhbi_final.hpp|8e7a351e8ee14a1a5511a99502f7d938296cc57c3757a74d7b45fc2071a63e0c|
|final/frozen_config.hpp|5efb54ce732ede2b9b25f7ea39240fccb95bdc08462733f89d3363c0473f6074|
|final/shared_allocator.hpp|66ad9ec278c27a07fcc8c63d00c303f46a48fe7ac4e26bdf801d7fca024c462f|
|final/adaptive_types.hpp|5bf2baa9fab583e3342fd45485d3770ac4e2a71d0abd5a88e63e15d34e78cabe|
|final_experiments/driver_core.hpp|91c332cb32a66b7195a0c28968eed7a9d703f5270e1ba72e8fa42868ae351c43|
|final_experiments/trace_cache.hpp|95ab6a9a695081085f64e2944fff32de2d72efb8a4ebe2e6eb93c5ea15f609a7|
|final_experiments/wall_driver.hpp|ca2bc88e7e891605d352531c0054c8f00d76b2e1ddef9940143bad275546aa03|
|final_experiments/legacy/generators.hpp|954cc8e923911926f1a689ba3eac2afd30c71351b87220713a62659d9730d6a6|
|final_experiments/legacy/pool_index.hpp|710202ee8396ac899d11cf3e3945ab5d630d8d86d3651cd7cec0da93bba45774|
|supplementary_20261007/horizon/manifest_start.json|092ce10b832129e9c405727be01a2a398b2740667b6ae68b5e4335c34ea0a6f8|

第一轮报告 SHA256=d931f06e31f5bc1c7488298c9f9f3436506a327524b12e86290e2113e890eed1，仍保留其否决结论与原输入绑定；本报告仅对当前修正字节作复审批准。

