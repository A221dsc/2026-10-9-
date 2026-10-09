# S1 驱动独立规格复审（Chunk 2，round 2）

日期：2026-10-09。**裁决：Approved，仅限 Chunk 2。MF1–MF3 已关闭；Critical：0；Important：0。** 可进入计划要求的独立质量审查。本裁决不批准 dev 选择、A/A、正式性能/机制/诊断矩阵或实验入口 READY。

本轮独立读取三处源码修复、新回归测试和实际 RED/GREEN/回归产物，比较首轮源码快照，重新核验哈希及受影响输出。没有修改 src/tests/tools、旧资产或首轮报告，没有重跑大型 suite 或运行任何 dev/A/A/性能/正式机制实验；新增文件仅本报告。只读执行包括日志/JSON/CSV/哈希解析，以及将已归档的真实 warning 和 frontend 日志传入当前 warning gate。

## 审查身份与范围

首轮 [S1_驱动规格审查.md](C:/Users/zhangjiacheng/Desktop/zjc/小论文/投稿准备/后续研究_20261008/S1/S1_驱动规格审查.md) 保持原字节，SHA256 `604d63b4511ef71c6bb9e1c4d6f5a3ad40c0be3ecba9401de650b5651721f257`。其 NotApproved 对应旧 `71332e…` source bundle；本次批准绑定以下新源码和完整 GREEN，不覆盖旧裁决。

下文路径均以 `C:/Users/zhangjiacheng/Desktop/zjc/小论文/投稿准备/后续研究_20261008/S1/` 为根。`G/` 为 `artifacts/driver/green_review_fixes_root_01/`，`T/` 为 `artifacts/driver/review_green_regressions_root_01/`。

| 新受审文件 | 当前实际 SHA256 |
|---|---|
| src/diagnostic_run.hpp | `221b576bf8d26b3076678c7bc79bde7221115fe10c5d796b8cd428675dbcf50f` |
| src/s1_driver.cpp | `80bed1e7790126c955b92e0ffb815f5839183fb742e554d4f256340e45892a5b` |
| tools/build_driver.py | `5dc8ffb8dfabc0f7bf22b0d413fed4cabdd5fce6ded98e16d2ef73d28a5569dc` |
| tests/test_driver_review.py | `a0144d0c0ec381670561eec7cccad78c97459ef9b65927c68b778aed133a9491` |

实际差分仅为 diagnostic_run 的 `(void)evidence_dir`、s1_driver 的 summary 可用性输出和 Original descriptor、build_driver 的 warning 门禁及受影响断言，以及新增回归测试。原 tests/test_driver.cpp 与全部内容/计时/生成/资源主体代码未改；没有删弱原断言。matched、diagnostic 内核分别仍为 `dbbcdad499564408574d284594ca6e253d3af8215e80f04b9260b7dcb575ba08` / `518dfcd5a0fcfe1b85564d892efbfac75f81b94de3b5f27ad9238ddcb20d0080`；冻结 production R6 仍为 `8e7a351e8ee14a1a5511a99502f7d938296cc57c3757a74d7b45fc2071a63e0c`。未重写 Chunk 1 裁决或规范。

本轮重算 10 个 S1/src 与 9 个冻结依赖组成的19文件 bundle：**`18667439ba0f6dafdefed29a5b8fff4671821b89dc9760773e1a5e4e592c7024`**。G 的20个 src/tests/tools 当前文件及快照、6个二进制、405个 evidence、9个冻结依赖全部0 mismatch。S0登记59个binding另重算0 mismatch，范围仍限已登记资产，不宣称扫描全部历史临时产物。

| 本轮依据 | manifest SHA256 |
|---|---|
| G/manifest.json：新完整 ENGINEERING_GREEN | `41a90f465a2bd30d8d9e92515b1c32234a8f0c6399026b4b44714d6906195405` |
| T/manifest.json：三个 MF 回归 PASS | `2404f0919fbab1e818cf1d5139b27bb0025e8eb33f179cfcc89588a37e2c1596` |
| artifacts/driver/review_red_capture_root_01/manifest.json：三个实际 FAIL | `44d884e4357d1689fb3c819574d0e043d3c10655cb314c0f2aa626c813bc71fc` |

G 的三个驱动二进制实际 SHA：native `b2c8a0d823af3428f298fefea7fa96c9ac0c04737261dfcc32a2860f4f85b6ef`；latency `785f86d88c2f3b7eb5d50b43b03b7351e7001ae12d1ac74fa026266dae593d46`；resource `f7413cfa0378683f0e605819ae6cc7df6989de64ee11a1f64ecc37da106dc25c`。actual describe/raw 的 binary/source 身份与它们一致。

## 三项修复裁决

| 首轮问题 | 实际实现与独立复核 | 裁决 |
|---|---|---|
| MF1：warning 被接受为 GREEN | [diagnostic_run.hpp:68](C:/Users/zhangjiacheng/Desktop/zjc/小论文/投稿准备/后续研究_20261008/S1/src/diagnostic_run.hpp:68) 用 `(void)evidence_dir` 消除 native 未使用参数 warning。[build_driver.py:9](C:/Users/zhangjiacheng/Desktop/zjc/小论文/投稿准备/后续研究_20261008/S1/tools/build_driver.py:9) 提取真实 `warning:`，L40–44 对实际 compiler 进程保存 warning 列表并调用拒绝门禁。六份 test/driver compile stderr 全部0 B，13个 compiler 进程实际 warning0。T 的真实 warning_probe 编译exit0却确有 unused 参数 warning；审查者只读调用当前 require_warning_free，确实抛异常拒绝该stderr，三份真实 `-###` frontend日志则正常通过。未新增全局 warning suppression。 | Closed |
| MF2：Original W descriptor 错误 | [s1_driver.cpp:39](C:/Users/zhangjiacheng/Desktop/zjc/小论文/投稿准备/后续研究_20261008/S1/src/s1_driver.cpp:39) 同时排除 Original/M_LIST。T 中13份实际 describe全部读取：这两个false，其余11个true，binary/source绑定正确。Original/M_LIST/R6三份native raw分别W=NA/NA/5958，与descriptor一致。未知方法仍由原validate_method拒绝。 | Closed |
| MF3：未测 owner/Original observer 指标伪0 | [s1_driver.cpp:27](C:/Users/zhangjiacheng/Desktop/zjc/小论文/投稿准备/后续研究_20261008/S1/src/s1_driver.cpp:27) 的resource_value只在resource输出数字，其余输出JSON字符串NA，resource_metric同步NA；observation对Original四个未接hook指标输出NA。审查者直接解析G中latency/resource × Original/M_LIST/R6六份summary，全部符合下表，M_LIST真实诊断W保留。资源采集和owner代码没有改动。 | Closed |

六份 actual summary 的关键值：

| mode / method | whole_peak / owner current / live after destroy | observer四项：W / buffer / epoch / candidate |
|---|---|---|
| latency / Original | NA / NA / NA | NA / NA / NA / NA |
| latency / M_LIST | NA / NA / NA | 5958 / 0 / 0 / 0 |
| latency / R6 | NA / NA / NA | 0 / 16 / 0 / 0 |
| resource / Original | 7464 / 0 / 0 | NA / NA / NA / NA |
| resource / M_LIST | 333400 / 0 / 0 | 5958 / 0 / 0 / 0 |
| resource / R6 | 333400 / 0 / 0 | 0 / 16 / 0 / 0 |

上表R6的observer W为外部LIST专用计数，R6实际W仍在raw中5958；它不替代或清零R6工作量。Original四账仍NA，resource全局请求字节实际可用。代表summary SHA：latency/Original `38bea2ae9cb67595f26053c2dd1f67f40924f23e604f33365ed60a2a3a112811`，resource/Original `f17b5575fcd582a1db5903a8e65ab7c7caef5c049209522f1b7fe0045d1b1652`。warning probe stderr SHA `7a96cd7ca05366c2f7d7719fd29939836bf89ed3c31ff77787c7deecaffb13ce`。

新回归 tests/test_driver_review.py L51–108使用实际compiler/describe/raw/summary产物；三个test结果均PASS，14个子进程均exit0（1个真实warning probe、13个describe）。回归所有输入和证据哈希均独立匹配，执行源码由完整G/source快照捕获。RED使用的原始测试另归档，实际SHA `df0625d7dad306714aed8b833336dd79df53f83daee1443fea3f620f8a837297` 与其manifest执行SHA逐字节一致；三个FAIL原因分别对应旧warning、旧Original descriptor和旧latency伪0，并可从旧实际产物独立复核。

RED总exit1另来自 root 保存的原exec_command工具返回receipt，路径 `artifacts/driver/review_red_capture_root_01/root_exec_receipt.json`，SHA `c82f3cdf2dfa35454c1d2be43a63c1a57e6f966f1b027a0ef14a030e94a4463c`。receipt注明来源为root转存工具结果、chunk05f825、原stdout三FAIL；不是child生成的process记录。其recorded_at是保存时刻，不冒充执行开始时间。原RED manifest保持原字节。

## 新完整 GREEN 与原主体回归

本轮没有只接受manifest布尔值：逐份读取35个suite的stdout完整PASS行、process exit0和空stderr；78个command为60个exit0、18个按设计拒绝exit2。与三个专门MF回归合计38项检查，不把13个describe子进程或warning探针误算成新的性能样本。

| 既有 Chunk 2 要求 | 新G实际证据/范围 |
|---|---|
| SX16 | 三mode均8192正事件/8192API，low W65400、high W50378922，PASS；生成器未改。 |
| SX17 | 三mode完整prefix8、4096queries、32768returned、API12288及range结构钟断言PASS。 |
| SX18 | 三mode完整F04 shape/old-alive/独立参考/cache往返PASS。actual cache SHA均仍为 `8f9dca592036437e1b9ce74c3832ecbde2841d898ad6891230f16a6abdb01289`，与首轮独立解析的262144单元/11604查询/535892API相同字节；未改为等长或缩小。 |
| SX19 | native PASS；actual native body SHA仍 `642963663303fdcf670efc57aad5c777378713e34319776c8a0d65102738b69c`，6处Clock、逐API额外Clock0、构造1、静态实例13。9份实际smoke raw的mask8/CPU3/group0与total/lifecycle算术一致。MF1/MF2关闭。 |
| SX22 | 三mode旧hot非空/K32满/budget stall/idle回收/B升/A返回/完整内容均1；NoIdle断言PASS。合法工程helper、正式M01生成规则都未改，未启动18正式回放。 |
| SX24 | latency/resource实际各14080样本，2promotion/1scheduled/1cleanup及完整轨迹/资源断言PASS；代码仅无效参数使用标记，无改策略或采集边界。MF3关闭，NA口径由实际summary验证。 |

actual三mode宏表仍为native NDEBUG、latency加S0_EVENT_TRACE、resource再加INDEX_MEMORY/ADAPTIVE_ALLOC_TRACK，无failure/ablation宏。flags与首轮逐项相同，统一-static/O3/DNDEBUG、compiler/runtime未换；静态runtime边界修复没有回退。新LLVM SHA `2474008025a03e3fdd6a50e3658162414fbbf553c6625ac6cc51b81acb0c31ab`。D01–D10及F/M登记registry/cached q规范的原suite均在新完整G实际PASS。

## 保留边界与最终裁决

首轮关于F01–F03仅工程scaled replay、registered默认核对、正式trace未齐；M01 generator与合法工程激活helper不同；诊断单桶无tie范围；旧runner必须后续适配0/1 REF/CAND到新1/2 A/B；raw selectedθ/h当前仅method阈值或NA；Chunk 3统计/选择/完整入口未开始等限制继续成立。本轮修复没有产生真实selection、A/A地板或正式矩阵结果。

旧 `green_complete_03` / `root_verify_before_review_01` 及失败attempt原样保留，其自报GREEN仍不满足首轮无warning准入，不能当本次最终合格G使用。首轮报告和本次报告分别绑定各自源码/二进制身份。

**最终：Approved（Chunk 2规格 round 2），三项Important已全部关闭，无新增must-fix。DEV_READY=false，FINAL_READY=false。**
