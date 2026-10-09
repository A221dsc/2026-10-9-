# S1 统计与入口规格审查 round2

日期：2026-10-09。**Verdict：NOT APPROVED。Critical：0；Important：2；Minor：0。** 首轮 MF1、MF2、MF3 的原始漏洞已关闭；新增的批次级身份/child 独立性及全批串行/冻结顺序缺口仍阻断 Chunk3 规格批准。统计公式、完整单 pair 侧车核验、选择重算、四种入口生命周期及 A/A 全批包络已有实质修复。65 项工程测试通过不能替代下述两项缺失的批次约束。

本裁决仅覆盖 SX20、SX21、SX23 的 Chunk3，不撤销内核/驱动的既有批准，不进入 quality review，不批准校准、A/A、正式性能、机制、延迟或资源矩阵。

## 1. 范围、版本与实际证据

唯一规范为 `S0_同布局比较合约_v1.md`、`S0_实验预注册_v1.md`、`S0_preregistration.json` 和 `S0_测试与指标覆盖矩阵.csv`。已读首轮 `S1_统计与入口规格审查.md` 的 NOT APPROVED 裁决；本轮重新完整读取五个工具 `analysis.py / select_dev.py / entry_gate.py / pair_adapter.py / run_engineering.py`，以及四个测试文件 `test_analysis.py / test_entry_hardening.py / analysis_fixture.py / red_analysis.py`，未把实现者总结当作规范或批准依据。

受审源码版本由 Git 管理：代码提交为 `37bfde7ccd58c45efdf249cdcd605fe2713965b0`，首轮基线为 `8b867c7`。保存本报告时当前HEAD为补充根验收/候选资产文档的 `18f2d716f4c5914952a617ddc12331ed2074ab92`；只读 Git 核验确认当前 `S1/src / S1/tests / S1/tools` 与受审代码提交仍无差分。本轮不建立新手工 sourceSHA 版本清单；以下 SHA 只标明既有归档 manifest 字节，旧 manifest 中的数据/binary/sidecar 完整性绑定继续有效。

|最终完整工程归档|Manifest SHA256|独立读取结果|
|---|---|---|
|`artifacts/analysis/green_complete_mf123_identity_01`|`4a4dbf6a93332eb71e2625a30c4b3d8ca0e474786da3d3cd340b7308a01daeb7`|65 tests / 32 actual processes；全部 exit0、逐测试 stderr 为 OK；9 当前源码与不可变快照一致|
|`artifacts/analysis/root_git_analysis_verify_final_01`|`7b97f674e3135d4348478ff3f2ad96a4016d1dd57e1efc7644bb92b390b5534e`|独立读取同样的 32 process 与完整 stderr，计数为65；全部 exit0、OK；9 当前源码与不可变快照一致|

两份归档共64份实际 process 与各自 manifest command 记录完全一致；其 process/stdout/stderr SHA 均与对应 evidence 记录一致。每份测试数为 Statistics 6、Sidecar 11、Prepare 8、Selection 3、AdapterGate 8、九个独立 HardeningSelection 9、HardeningManifest 4、HardeningAA 3、HardeningHistory 1、HardeningFinalAnalysis 1、SelectionRed 2、ManifestRed 1、AABeforeRed 1、HardeningTiming 3、HardeningPhaseClosure 2、HardeningSelectionLink 2，共65。

每份最终 manifest 的 evidence 清单有29258个文件。本审查没有再逐个哈希整个清单；本次独立核验范围是上述全部 process/stdout/stderr、9份当前/快照源码及必要既有 fixture。根代理另外完成 root 归档的29258文件核验并报告0 mismatch，此为补充验收信息，不冒充本审查重新遍历的结果。root 原工程 runner 的父 session 已退休，不能据完成 manifest 推断其父进程退出码；这里的成功事实依据是实际32子进程、完整逐测试 stderr 和完成 manifest。

两份最终 manifest 的全部实验计数均为0，`DEV_READY=false / FINAL_READY=false / selected_theta=null / selected_h=null`；`entry_validation_fixture.json` 同样列出真实入口资产缺项。复用来源是完整 `green_complete_mf123_01/dev_fixture`，其9121个开发 fixture 文件由工程 runner只读校验后引用，依然是 `test_fixture=true`。`red_selection_link_01` 超时后保留的完整字节只用于测试，不能成为 production 证据。

本轮只新增本报告。未修改源码、测试、旧报告、S0、Git 或四个候选工程资产；未重跑大型套件、构造240 fixture、启动任何被测二进制或执行计时矩阵。小型复现仅读取已有文件并在内存中组合预制字节。

## 2. 首轮三个 Must Fix 的复核

### MF1：Closed，批次独立性另受 MF4 阻断

`select_dev.py:18–52` 仍要求240个不同锁路径、准确30×8开发 cell、native/dev、M_LIST直接 reference、同输入缓存字节及共享 binary/protocol/source/config，重算八个等权 `mean(log(two_round_total_ratio))` 分数。L12–16 的 tuple 排序只在 float 分数精确相等时取小门槛；没有 epsilon tie 或以 online 替代 total。L81–87 使用 exclusive-create，fixture 只许 `*_fixture.json`，production writer只许 `dev_selection.json`。

新增 `verify_selection`（L54–79）要求生产原始文件和独立外部冻结 SHA，对全部240 pair重新调用 production `validate_pair`，逐字段比较八分数、θ/h、30输入缓存、所有 identity bindings、binary/protocol/source/config、矩阵时间及冻结规则。改外层 `test_fixture=false` 和重新哈希不能把240个内层 fixture变为生产选择。`entry_gate.py:446–456` 的入口 wrapper绑定并读取该原始 write-once记录，没有另算一份同值收据代替它。

`entry_gate.py:281–284、457–463` 要求 formal completion绑定当前 readiness 的同一原始 selection路径及字节；`analysis.py:130–137` 要求 P06/P07 使用 A/A所绑定 formal matrix中的同一 selection文件，再调用完整选择重算。最终 GREEN同时包含错误分数/阈值/绑定拒绝、重新哈希的 fixture伪装拒绝、write-once wrapper闭合、相同原始selection接受及不同原始selection拒绝。首轮 MF1的 fixture/错误选值漏洞已修复；“960 child均独立”不能由240×4的名义计数自动成立，见 MF4。

### MF2：Closed，完成证据的身份映射另受 MF4 阻断

`entry_gate.py:464–506` 不再只检查 `entries` 非空。selected_configs要求恰好两个选定方法、正确θ/h、完整原生配置对象、逻辑/文件 SHA、冻结 R6参数、native binary与source/protocol，并跨资产绑定已验证选择、binary和source（L281–327）。

开发开始计划要求准确240 cells；正式开始计划要求准确700 cells，即560主配对加140未调诊断配对。L493–506 核对唯一完整 `(case_id, seed, pair_id)` 集合、4 children、NOT_RUN、batch/profile、注册方法、实际cache/expected/meta路径与SHA、每个方法的binary/config/source/protocol；正式选定配置再与已重算选择绑定。完整集合由计数与集合同时约束，不能以重复某格补齐另一格。

最终 GREEN中的 HardeningManifest实际验证完整240/700预制开始计划及selected配置，拒绝重新哈希后的缺字段、缺格/重复格、错误batch/method/status/trace绑定及错门槛/config/binary。此为schema/绑定行为测试；700完成矩阵的GREEN测试只覆盖shape helper，未执行全700生产完成验收。原始“仅非空或bool即通过”的漏洞已关闭，完成证据跨cell独立性见 MF4；开始条目/实际执行顺序见 MF5。

### MF3：Closed，跨 pair 全批串行另受 MF5 阻断

`entry_gate.py:576–650` 明确分开 `scope × phase` 的2×2生命周期：

|入口|实际要求|
|---|---|
|dev start|完整开发开始计划、当前环境收据新鲜度≤300秒、完整before A/A；不要求after|
|dev complete|完整且重算的开发选择、原开发环境/开始计划、完整before+after A/A及重算地板；A/A实际区间包围整个选择矩阵|
|final start|已完成dev历史，使用独立冻结的dev历史环境、同一选择及selected配置；另有当前新鲜环境、正式开始计划和完整formal before A/A|
|final complete|另有完整700 formal pairs及完整formal before+after A/A，重算formal地板；A/A实际区间包围整个formal矩阵|

`_aa_pair_identity`（L330–332）拒绝latency/resource模式，要求native、AA profile、seed92001、同方法。库存L399–430保持注册profile×五block×两轮×A/B集合，并由实际侧车重算全profile最大绝对log比值有限包络。L334–337、544–574用所有pair的min-start/max-end，要求 before结束≤矩阵开始、矩阵结束≤after开始；不允许提前完成after后再执行矩阵。

L407–411要求completed AA保留原before库存的路径/SHA、同batch/environment及完全相同的before entries；L292–299在重验原开始计划时继续解析原before绑定，completed AA文件不会迫使覆盖开始清单。生产final summary必须有完整AA及full700 matrix；fixture只在显式test模式接受，不授权生产解释。最终GREEN覆盖上述native拒绝、缺after拒绝、错误floor拒绝、提前after拒绝、dev complete缺选择拒绝及原before绑定存活行为。四种生命周期的首轮循环/缺闭合问题已修复；min/max包围关系本身不证明全批进程串行，见 MF5。

## 3. 新增必须修复项

### MF4 / Important：不同逻辑 pair 可以复用实际 child，完成 entry 标签未闭合到执行身份

规范锚点：预注册L60规定960个dev主计时子进程；L74要求选定值等于16/128时仍保留独立诊断执行；L76禁止合并同输入不同pair的独立reference运行；L116规定缺失/重复child停批。SX20要求完整选择批次，SX23要求完整合格pair证据。

实现锚点：`entry_gate.py:184、195–202` 只验证单锁内部四个不同child与锁自身pair_id；`select_dev.py:20–40` 验证240不同锁和不同开发cells，保留child bindings却不跨锁去重或核对注册cell到实际执行pair身份。`entry_gate.py:344–374` 要求700不同锁路径，L361–370仅比较case/seed/profile/mode/method/batch及冻结来源，没有比较entry的pair标签与锁内/raw/process执行pair身份，也没有统计全700唯一child。

**已执行的小型只读内存复现：** 使用完整GREEN来源中D01/90001的M_EVENT_16与M_EVENT_32两个既有fixture。把第二锁的两个A/reference child指向第一锁的A child，统一相同资产路径/内部pair_id，并仅在内存重绑第二锁B child的raw/phase/process字节及SHA。通过Path读取适配器读取这些内存字节；未替换 `validate_pair`、任何语义判断或统计函数，未写入文件。两个原函数调用 `validate_pair(..., test_fixture=True)` 均成功，两个开发候选cell仍不同，但两锁只有6个不同child目录，名义计数是8。

此复现证明单pair完整性不能阻止跨pairreference复用；它是工程fixture行为，**不是**全240或700生产验收成功的声明。生产分支另有fixture/trust/注册缓存/冻结driver检查，但这些分支不增加跨锁child集合或注册执行身份检查。对于同case/seed的真实同输入，reference本来就具有相同方法、缓存、binary与config，完整字节绑定无法补上缺失的“必须另跑reference”要求。

**正式矩阵的构造性证明（未执行全700）：** 若θ=16，则P06与DIA01的方法均为M_EVENT_16→R6；若h=128，则P07与DIA02均为M_FIXED_128→R6。把一个完整合格锁的相同字节冻结在两个不同锁路径，分别填入这两个entry标签，其四个实际child仍是同一组。当前shape判断只区分锁路径和entry cell；两次 `validate_pair` 的所有单锁判断与external SHA均可保持相同，L361–370的全部比较也相同，而L371以caller提供的entry标签构造两个matrix_cells。因此在其余698格合格的条件下，循环中没有能识别这组重复执行证据的判断。不能以两个独立manifest路径代表八个独立实际child。

修复验收范围：

1. 开发240 pairs及正式700 pairs都要跨锁核验实际child唯一，分别得到960和2800个不同child；不能共享reference运行、复制锁路径或用不同entry标签重复同一执行证据。
2. 开始清单的注册cell必须可核验地映射到完成锁、所有raw/process中的执行pair身份。若内部pair_id采用复合串，应冻结明确映射；不额外发明新的统计标签或改变S0注册集合。仅对caller的entry标签做集合校验不够。
3. 正式P06/DIA01、P07/DIA02在选值重合时仍必须是两个独立四child配对。补充“复制锁不同路径”“共享两个reference child”“entry标签错配但方法相同”的重新哈希RED，以及真正独立证据的接受GREEN；不需要为此运行性能矩阵。

A/A库存已有跨block `pair_ids` 唯一检查（L418），且单pair raw身份绑定使上述相同路径共享child的简单构造会触发重复pair_id；本轮没有发现A/A同类的直接身份绕过。不要把这一结论扩大到尚未审查的物理文件alias情形。resume的完整单pair规则保持原样，不能把跨cell复用解释成合法resume。

### MF5 / Important：全批实际串行及登记顺序没有验证，min/max包络会接受重叠批次

规范锚点：预注册L60冻结dev候选次序及D/seed外层升序；L76冻结正式case、seed、pair_id升序；L90要求所有计时串行。JSON的 `timing.pair_schedule` 与 `all_runs_serial=true` 是同一约束。

实现锚点：`entry_gate.py:226–228` 的previous_end只存在单pair四child循环内部。`select_dev.py:30、51`、`entry_gate.py:372–374、419–421` 对不同pair只保存min/max，没有跨pair时间区间不相交的判断；`_aa_order`（L334–337）只证明三个大区间的包围关系。开发选择/完成、正式full700 completion和同一时点多个AA blocks均可保持单pair内部AB/BA合法，却彼此并行。

**已执行的只读检查：** 两个原样既有fixture的child路径交集为0，原函数各自完整核验成功，但其实际fixture区间均为 `(started_ns=1, ended_ns=32)`。将这种两个重叠pair的min/max `(1,32)` 传给原 `_aa_order`，before结束0、after开始100时它接受。测试用时钟是预制值，不是真实实验；它说明现有共享判断只识别包络，不识别pair间重叠。源码中没有另一个批次串行守卫。最终GREEN的此类预制时间戳不能作为真实全批串行证据。

实际执行顺序同样缺少验证。`_formal_matrix_shape`（L344–346）只核对集合，原函数接受反转后的700条内存条目；**完成库存的entries数组本来可以无序，这一shape结果本身不是规格反例。** 真正阻断在于full700循环也没有根据已核验的实际进程起止时间检查注册cell先后；即使全部pair串行，按逆序执行的时间证据仍没有相应拒绝判断。`select_dev.select` 同样没有从不同pair的实际时间验证注册候选次序。`start_manifest`（L493–506）只验证条目集合，没有冻结可用于执行的注册顺序。

当前 `test_entry_hardening.py:172–175` 的formal `schema_context` 示例按 `P01..P08,DIA01,DIA02` 插入，而预注册L76是核心与诊断统一按pair_id升序，即同一case/seed内应为 **DIA01,DIA02,P01,P02,P03,P04,P05,P06,P07,P08**。`entry_gate.py:340–342、487–489` 同样使用P在前、DIA在后的字典，但这些字典当前用于查表，不能据此声称实际生产已经错序；问题是接受门和测试模板没有保护冻结顺序，不能把该模板次序当成规范。

修复验收范围：

1. 对已选开发attempt、正式700完成pairs以及AA各timepoint的所有实际child建立批次串行检查；不同pair的完整执行区间不能重叠。继续保留pair内部AB/BA顺序和AA对全矩阵的前后包围约束。
2. dev按D01..D10、seed数值升序、注册候选索引E8/E16/E32/E64/F128/F512/F2048/F8192检查实际chronology；不能把candidate方法字符串直接lexicographic排序替代注册索引。
3. formal按case_id、seed数值、pair_id升序核对实际chronology，包含全部十个主/诊断标签；开始计划也要生成并冻结同一执行顺序。给同方法的selected与diagnostic独立执行身份，不能因阈值相同合并或调换。完成库存的JSON数组无需新增排序限制，应依据实际process时间证明已执行顺序。
4. AA未登记同一timepoint内profile的方法/case顺序，不额外添加该顺序要求；仍须完整注册profile/五blocks、全批串行、before/after位置与原before绑定。开发/正式仍用各自独立地板。
5. 补“两个完整pair重叠”“AA同一timepoint blocks重叠”“serial但dev候选错序”“serial但formal主/诊断标签错序”的预制RED；正确序列接受GREEN。不要只对输入列表排序后忘记比较真实process时间，也不要通过改变S0顺序解决测试失败。

## 4. RED、GREEN的证据边界

|归档|实际读取的失败/成功|证据用途|
|---|---|---|
|`red_entry_mf123_02`|4 tests / 3 processes均exit1；fixture/错误选值被接受、空entry被接受、完整before被拒均为实际AssertionError|首轮三MF真实RED|
|`red_final_aa_contract_01`|1 test / exit1；旧summary缺aa_inventory参数，经self.fail成为AssertionError|入口接口缺闭合的RED；不声称旧实现真的接受了该before文件|
|`red_aa_process_order_01`|3 tests / exit1；其中提前after被接受导致“ValueError not raised”是真实行为；另外两项缺helper|只把提前after项作为时序行为RED；缺helper不冒充模式/700行为反例|
|`red_phase_closure_01`|2 tests / exit1；dev complete缺选择依赖、completed AA导致原start绑定失效|生命周期闭合RED|
|`red_selection_link_02`|1 test / exit1；不同selection文件被接受，“ValueError not raised”|同原始selection身份RED|
|`green_complete_mf123_01 / timing_01 / final_01`|分别58/28、61/29、63/30 tests/processes，全实际exit0|阶段性完整GREEN，不能代替当前65/32快照|
|`green_selection_link_01 / green_selection_link_positive_01`|各1 test / exit0|局部错记录拒绝/同记录接受；不能独立代表完整GREEN|
|`green_entry_hardening_attempt_01 / 02`、`red_selection_link_01`|存在55秒timeout、exit124；后者0 completed tests|保留失败，不算通过或行为RED|

后续task=entry的RED归档在runner策略中记为ENGINEERING_FAILED；这里按实际断言和退出码辨认，不改标签，也不因为名称含RED/GREEN就采信。新增MF4/MF5的内存检查没有生成新的工程RED归档，不把它冒充全套RED或生产验收。后续应以新immutable tag保存限定范围RED→GREEN，再独立复审。

## 5. 逐SX裁决及未放行状态

|项|通过部分|本轮裁决|
|---|---|---|
|SX20|30×8集合、八total分数、exact-float tie、θ/h/来源绑定重算、write-once、生产拒fixture、同原始selection闭合|原MF1关闭；完整开发批次的独立child与实际顺序仍被MF4/MF5阻断|
|SX21|两轮log几何、10输入median/线性IQR/wins、sample SD/df9、42确认族与其余95%条件CI、log/ratio端点尺度、all10严格5%及AA logfloor判读、有限AA包络、缺失/重复/非正/invalid隔离、慢与unresolved保留|统计核心通过；用于生产判读的批次合法性须随MF4/MF5关闭|
|SX23|全侧车及cache/source/binary/config字节与身份、固定mask8/CPU3/group0、命令/退出/NA/预算/phase求和、完整pair resume、环境新鲜度及历史环境分离、2×2生命周期、原before存活、full700及同原始selection要求|NOT APPROVED：新增2项Important阻断|

少数直接 `Path.read_bytes/read_text` 调用的文件消失仍可能抛OSError，readiness未统一把所有这类异常转换成missing reason；已做SHA/load等路径的ValueError转换不能概括所有直接读取。此行为中止验证、保持fail-closed，不会把不完整资产变为READY；本轮将其列为非阻断维护concern，未计为规格反例或额外Must Fix。

四个候选 `S1_GREEN_记录.json / S1_资产清单.json / S1_覆盖执行记录.csv / 工程入口清单.md` 不作为本轮批准凭据。真实dev/final trace全集、实时quiet环境、真实write-once选择和真实完成矩阵仍未执行。修复应保持Git管理源码、保留当前HEAD/旧报告/所有旧attempt、不改R6/C++、S0或统计/sidecar/fixture/环境/resume规则；新增限定MF4/MF5的工程证据后进入round3。本轮结束于本报告，不开启quality或任何实验。
