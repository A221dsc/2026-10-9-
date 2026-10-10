# S1 统计与入口规格审查 round3

日期：2026-10-09。**Verdict：Approved。Critical：0；Important：0；Minor：0。MF1、MF2、MF3、MF4、MF5 均 Closed。** 本轮批准 S1 Chunk3 的统计与入口规格实现；round2 的两项 Important 已由批次独立性、注册执行身份及实际时间顺序核验关闭。批准依据是冻结规范、当前源码、实际 RED→GREEN 日志和小型只读复核，不是归档名称中的 GREEN。

本裁决只覆盖 SX20、SX21、SX23，不进入 quality review，不批准执行校准、A/A、正式性能、机制、延迟或资源矩阵。当前真实 `DEV_READY=false / FINAL_READY=false / selected_theta=null / selected_h=null`，全部实验执行计数仍为0。

## 1. 规范、版本和读取边界

唯一规范仍为 S0 的 `S0_同布局比较合约_v1.md`、`S0_实验预注册_v1.md`、`S0_preregistration.json`、`S0_测试与指标覆盖矩阵.csv`。对照首轮 NOT APPROVED 报告及 round2 的 MF4/MF5 验收范围，没有以实现者说明或候选入口资产替代规范。

受审源码由 Git 管理，提交为 **`b9f5bd9a8e8e8330fc645abaf4a5a1ffdf7d2c3d`**。只读 Git 核验确认当前 `S1/src / S1/tests / S1/tools` 与该提交没有差分；与 round2 的 `37bfde7ccd58c45efdf249cdcd605fe2713965b0` 比较，S0 和 C++ `S1/src` 没有变化。没有新建手工 sourceSHA 版本表；既有 manifest 的 SHA 继续用于字节完整性和历史证据绑定，不替代 Git 版本。

本轮完整读取五个工具 `analysis.py`、`select_dev.py`、`entry_gate.py`、`pair_adapter.py`、`run_engineering.py`，以及五个测试 `test_analysis.py`、`test_entry_hardening.py`、`analysis_fixture.py`、`red_analysis.py`、`test_batch_hardening.py`。已检查 production 与显式 `test_fixture` 分支；本轮没有构造240/700 fixture、调用大型 collector、运行完整套件或启动被测二进制。只新增本报告，未修改源码、测试、S0、旧报告、Git 或候选工程资产。

|归档|实际 process / tests|本次独立读取结果与用途|
|---|---|---|
|`batch_fixture_mf45_01`|20 / 22|实际准备进程均 exit0；仅为完整预制 dev/formal fixture 的只读复用来源|
|`red_batch_mf45_01`|8 / 8|全部 exit1；八项均为实际 `AssertionError: ValueError not raised`，不是 timeout 或缺 helper|
|`green_batch_mf45_01`|11 / 11|全部 exit0、OK；包含三项身份拒绝、五项顺序/串行拒绝和三项正例|
|`green_complete_mf45_01`|43 / 76|全部 exit0、OK；阶段性完整 GREEN，不替代当前77项快照|
|`red_aa_array_mf5_01`|1 / 1|实际 exit1；合法 completed AA 数组重排被旧实现拒绝，经 `self.fail` 成为 AssertionError|
|`green_aa_array_mf5_01`|1 / 1|实际 exit0、OK；数组重排接受，原before完整内容变化和重复仍拒绝|
|`green_complete_mf45_final_01`|44 / 77|全部实际 exit0、OK；10份当前源码、不可变快照和 manifest 绑定一致，最长进程41.6878716秒|

以上归档的全部实际 process、stdout、stderr 均已读入核对；process 与 manifest command 一致，三个日志文件的 SHA 与登记 evidence 一致。最终完整归档的 manifest SHA256 为 `625e41f2c4dcc2c2a4b82f85ff029941da059eb16277a1468fff34c1cbcaf3cb`。77项为原65项加11项 BatchIdentity/BatchChronology/BatchPositive及1项 BatchAAOrder，实际44个进程的退出与逐测试结果支持该计数。

RED 的旧源码身份也有独立 Git 字节核对：`red_batch_mf45_01` 的四个核心语义工具（analysis/select_dev/entry_gate/pair_adapter）快照等于 Git `37bfde7`；`red_aa_array_mf5_01` 的同四工具等于 `ab8a799`。测试派发 runner `run_engineering.py` 已调整，不能概括为五个工具都等于旧版。后一个 RED 保留 `ENGINEERING_FAILED` 和 `source_snapshot_unchanged=false` 的聚合字段，本报告没有改写它们，也没有把该字段当作核心语义源码变动的证据；其行为 RED 由实际异常及旧 Git 字节身份共同限定。

最终 manifest 登记43193份 evidence，复用来源登记35722份 fixture 文件。本审查没有重复遍历这两份全清单；独立核验范围为上述全部日志、10份当前/快照源码、S0四资产当前绑定和下述少量既有 pair。根代理另报告最终归档全43193份证据0 mismatch及来源35722份只读核验，此为补充信息，不冒充本审查重新遍历结果。

根另跑的 `root_git_analysis_verify_mf45_final_01` 在本次读取时尚无完成 manifest；本审查随后实际读到其中 `BatchIdentity.test_copied_lock_is_not_an_independent_diagnostic` 的process为55秒timeout、exit124，stderr为 `ENGINEERING_TIMEOUT_55_SECONDS`，没有完成测试结果。**该新attempt不能称GREEN，不纳入本报告的通过声明，也不推断其runner父进程退出码。** 保留该失败，后续根验收另行闭合；它不是“ValueError not raised”等语义反例，不能冒充新的行为RED，也不以超时为由放宽55秒预算或改变源码。本轮规格裁决仍依据已完成的77/44归档、当前源码及明确的语义核验范围。

## 2. MF4：Closed，独立 child 与注册执行身份闭合

规范锚点：预注册L60的960个独立 dev 主计时子进程、L74的选值重合仍独立诊断、L76不得复用不同pair的reference运行、L116缺失/重复child停批；SX20及SX23。

`entry_gate.py:144–257` 保留原完整单pair验证，生产分支仍要求独立外部锁/来源信任、真实注册cache、冻结driver/native binary及全部侧车字节。L195–202的 raw 身份与锁一致，L231–233的实际命令、stdout/stderr与锁一致。新增 L228–229及L254–257返回四个已验 child 的 canonical path、实际 `(batch_id, attempt_id, pair_id, round, role)` 身份和进程区间，没有用未核验 caller 字段代替侧车。

统一 `validate_batch`（L259–288）对每个批次检查两种独立性：L273–275同时拒绝 canonical child path 或实际执行身份元组重复；L278要求同一batch且每pair恰好四个不同child。复制锁到另一条manifest路径、复制child字节到另一条目录但沿用实际执行身份，都不能充当另一次执行。L276–277进一步要求完成锁的执行pair_id等于注册cell映射。

`pair_adapter.py:13–23` 冻结映射为 `case_id:seed:cell_id`，其中 dev cell 仍是注册候选，formal cell 仍是 P01..P08/DIA01/DIA02；没有增加统计标签或改变比较对象。该身份通过原单pair核验贯通锁、raw、phase及实际CLI/process。开始计划 `entry_gate.py:546` 和正式完成entry L398–400也核对同一映射；最终批次L277再核对entry cell与完成锁，不会仅因entry声明了正确字符串就通过。

所有收集入口均实际接入该共同判断：

|入口|当前源码|
|---|---|
|dev选择/原记录重算|`select_dev.py:19–43、57–81`；完整240锁、30×8唯一cells后调用 `validate_batch(scope='dev')`，明确要求960独立child|
|正式完成|`entry_gate.py:383–412`；完整700唯一cells、每格完整pair及跨dev来源绑定后调用 `validate_batch(scope='final')`，明确要求2800独立child|
|dev/formal A/A库存|`entry_gate.py:434–471`；完整注册profile/block集合、单pair合格及独立pair_id后调用 `validate_batch(records)`|
|最终单格统计|`analysis.py:113–155`；十个完整输入、与全formal矩阵同格同锁SHA之后调用 `validate_batch(scope='final')`；生产AA验证会先读取完整700正式矩阵|

上述批次判断不因 `test_fixture=true` 被跳过。fixture模式只提供预制证据；production仍要逐层外部冻结、真实cache及binary核验，不能把外层标志改为false后使用内层fixture。

`test_batch_hardening.py:79–107` 的RED→GREEN实际覆盖：不同路径复制P06锁充当DIA01、相同方法的P06/DIA01及P07/DIA02错配、跨dev候选共享两个reference child。L143–156的正例调用真实实现，证明同方法P06/DIA01拥有不同执行身份和八个不同目的地，完整240 dev接受960child，完整700 formal collector接受700独立锁/cells。其θ16/h128只是测试选择，不是真实校准结果。P07/DIA02同方法的错误映射另有实际拒绝覆盖，生产映射及去重守卫对两个标签同样适用。

本审查另只读调用当前原函数，读取既有D01/90001 E8与E16及GREEN保留的损坏锁：共享reference构造仍可分别通过单pair核验，但双pair批次实际拒绝 `independent batch children required`；单独完整合格的复制P06锁映射到DIA01时实际拒绝 `registered cell/execution pair identity mismatch`。没有重跑全240/700。这与实际完整collector测试日志及源码共同证明round2的身份缺口关闭。

## 3. MF5：Closed，全批实际串行、注册顺序与无序完成库存

规范锚点：预注册L60固定dev候选及外层case/seed顺序，L76固定正式case/seed/pair_id升序，L90所有计时串行；JSON的注册候选数组与串行约束。AA同一时点内没有额外profile排序规范。

`entry_gate.py:279–286` 从已验process起止时间排序完成pair，核对完整pair区间不重叠，再将**实际时间序列**与注册cell次序比较。完整pair区间检查也禁止不同pair的四个AB/BA child交错；原L226–227的pair内部串行仍保留。`select_dev.py:54` 和formal L411的矩阵区间直接来自该已验批次，AA前后包络不再用未经串行核验的min/max替代批次合法性。

`pair_adapter.py:25–30` 的dev顺序是case、数值seed、注册候选数组索引，准确为E8/E16/E32/E64/F128/F512/F2048/F8192；没有用候选字符串字典序代替它。formal顺序是case、数值seed、pair标签词典序，同一输入为 **DIA01,DIA02,P01,P02,P03,P04,P05,P06,P07,P08**。开始计划 L539–546要求完整唯一集合、同一注册顺序和执行身份。`test_entry_hardening.py:177–182` 的计划模板也已采用该口径，未改S0来迁就原P在前模板。

正式完成库存数组不必排序：collector读取全部已验process，然后比较真实chronology。`test_batch_hardening.py:155–156` 的正例确实反转700条完成entries并调用完整 `verify_formal_matrix(..., test_fixture=True)`，不是只调shape helper；实际日志为OK。dev L153–154反转输入路径同样被完整selector接受。数组重排没有改变真实执行时间和来源绑定。

AA调用 `validate_batch(records)` 不传注册排序scope，故仅强制全批实际串行，没有发明method/profile排序。原 `_aa_order`（`entry_gate.py:368–371`）、dev completion L593–606、final AA L608–623保留同batch的 before结束≤整个矩阵开始、整个矩阵结束≤after开始；production final仍要求完整700。AA库存及原before绑定的数组处理也已修正：L446–452继续核验原文件路径/SHA、fixture身份、batch/environment及唯一完备before集合；L455按注册cell排序后比较**完整条目字典**，允许完成数组载入顺序不同，不允许改任何条目字段。开始计划通过L320–335仍使用原before文件绑定，不会因completed AA文件出现而改绑。

`test_batch_hardening.py:110–140` 的真实RED→GREEN覆盖start计划错序、dev overlap、dev串行但候选错序、formal串行但主/诊断错序、同一时点AA blocks重叠。L159–183另覆盖合法completed AA重排接受、完成数组重复拒绝、重新哈希的原before完整内容变化拒绝、原before重复cell拒绝。`red_aa_array_mf5_01` 是正例误拒的实际RED；修复只取消数组顺序这一额外限制，没有取消文件/完整内容/唯一集合约束。

本审查小型只读复核也直接运行当前 `validate_pair`/`validate_batch`：

|既有证据组合|实际结果|
|---|---|
|D01/90001 E8区间2000..2007、E16区间2040..2047，反向载入|接受8独立child，区间2000..2047|
|单pair各自合格，E16改为2003..2010|拒绝 `all batch pairs must run serially`|
|E8在2040..2047，E16在2000..2007，互不重叠|拒绝 `registered actual batch chronology required`|
|F01/91001 DIA01在20080..20087，P01在20000..20007，互不重叠|拒绝 `registered actual batch chronology required`|

这些是已有工程fixture的预制时钟，不是实际性能进程观测；它们验证接受门语义。全700行为依据上述实际collector测试日志，未声称本审查执行了全700生产完成验收。

## 4. MF1–MF3 回归复核

**MF1：Closed。** `select_dev.py:19–55` 保留240不同完整锁、准确30×8、native/dev、M_LIST直接reference、共享输入和binary/protocol/source/config，评分仍为30个两轮total比值的等权mean log。L13–17只在float精确相等时按小门槛取值，没有epsilon tie或目标变更。L57–81重新核验生产原始记录的全部240pair、八个分数、θ/h、identity bindings及矩阵区间；L84–90仍exclusive-create write-once。`entry_gate.py:315–318、492–509`及 `analysis.py:130–137` 保留readiness/formal/P06/P07对同一个原始selection文件路径和SHA的闭合，不接受同值不同文件替代。当前77项完整GREEN仍包含fixture伪装、错误分数/选值/绑定拒绝和同原始selection接受/错记录拒绝。

**MF2：Closed。** `entry_gate.py:345–362、510–555` 保留恰好两个selected配置、完整原生参数对象、逻辑及文件SHA、固定R6参数、选定θ/h和binary/source/protocol跨资产绑定。开始清单仍为完整唯一240/700注册cells，核验batch、NOT_RUN、profile、四child、输入cache/expected/meta的实际路径与SHA、各方法配置及原before环境绑定。新增注册身份及计划顺序是对原完整集合的约束，没有退回非空/bool判断。完整manifest损坏拒绝测试仍在77项中。

**MF3：Closed。** `entry_gate.py:593–699` 仍区分四种生命周期：

|scope × phase|保留的要求|
|---|---|
|dev start|完整dev计划、当前新鲜环境≤300秒、完整native before AA|
|dev complete|完整重算选择、原dev开始/环境、完整before+after AA与地板，包围完整选择批次|
|final start|完成dev历史及独立历史环境、同原始选择及selected配置，另有当前新鲜环境、正式计划和完整native formal before AA|
|final complete|另有完整700正式完成证据及完整native formal before+after AA，包围整个正式矩阵|

历史环境L652–655和完成解释L613使用独立绑定且不伪造当前新鲜度；当前开始仍按300秒核验。AA L364–366仍native/AA/seed92001/同方法；完整库存仍按注册profiles×五块×两轮A/B核验并重算有限log包络。提前after、缺after、错误floor、dev complete缺selection和原before绑定失效的回归测试仍通过。测试模式的 `test_matrix` 或省略production trust只在显式fixture路径可用，readiness L670拒绝fixture，生产summary L117及L611–621不省略完整AA/full700。

## 5. 逐SX裁决与限制

|项|本轮规格裁决|
|---|---|
|SX20|Approved：完整30×8/240锁/960独立child、注册实际顺序、八total分数、精确tie、原始write-once selection及全部绑定；真实选值尚不存在|
|SX21|Approved：两轮log几何；十输入median/线性IQR/wins；sample SD/df9；P03/P06/P07×七场景×online,total的42确认族及其余95%条件CI；log/ratio端点尺度；all10严格5%和AA logfloor；有限AA包络；缺失/重复/非正/invalid拒绝，慢与unresolved保留。批次证据合法性现由MF4/MF5守卫闭合|
|SX23|Approved：完整侧车/命令/退出/亲和性/phase/预算/NA/来源输入配置binary绑定、注册执行映射、全批独立且串行、2×2入口、环境新鲜度及历史分离、原before存活、完整700与同selection、完整合格pair resume|

统计核心 `analysis.py:1–111` 的公式和判据没有因MF4/MF5修复而改变；改动在证据收集合法性。候选、方法、成本/算法、R6参数、负载和冻结C++未改。`validate_pair` 的failure/缺receipt/SHA不符使完整pair不能resume；本轮未增加选择性重跑、拼接attempt或复用其他cell reference的例外。旧失败attempt和RED标签保留。

`run_engineering.py` 仍以工程任务白名单、immutable tag、逐进程55秒上限、实际输出及源码快照归档；新增派发是预制fixture行为测试，未变成实验入口。最终归档仍准确报告实验计数0及真实两个READY=false、θ/h=null。四个候选工程资产和根验收文档不是本裁决的批准凭据。

文件在读取时消失仍可能由个别直接Path调用抛OSError，未统一转换为missing reason。该路径fail-closed，没有产生fixture放行或不合格pair通过的规范反例；保留为非阻断维护concern，不新增Must Fix或改变本轮批准范围。

**本轮全部五项Must Fix已关闭，Chunk3规格Approved；质量评审和真实实验入口仍须各自独立处理。**
