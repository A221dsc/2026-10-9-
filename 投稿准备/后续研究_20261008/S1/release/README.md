# S1 驱动的 Git 版本快照

这三个 Windows x64 驱动来自已通过独立规格与质量审查的 `artifacts/driver/green_review_fixes_root_01`。复制后使用 Git 对象的字节比较核对一致；发布版本由 Git 提交和最终阶段标签定位，不另建手工源码或二进制 SHA256 版本清单。工程源码、三个二进制及最终验收记录由 `s1-engineering-v1` 定位；源码提交为 `b9f5bd9`，本轮工程复核和独立审查均已闭合。

|文件|用途|
|---|---|
|`binaries/s1_native.exe`|原生 build / online / total 计时|
|`binaries/s1_latency.exe`|独立操作及转换延迟诊断|
|`binaries/s1_resource.exe`|独立延迟、内存及所有权诊断|

构建源码为 Git 提交 `8b867c7` 中的 S1 C++ 源码及共享冻结依赖；后续统计/入口修复没有修改这些构建输入。正式编译参数为 `-std=c++17 -O3 -DNDEBUG -Wall -Wextra -Wno-unknown-pragmas -Wno-misleading-indentation -Wno-unused-function -static -municode`。latency 启用 `S0_EVENT_TRACE`；resource 另启用 `INDEX_MEMORY` 和 `ADAPTIVE_ALLOC_TRACK`；native 不启用这些诊断宏。编译器是本地冻结 LLVM-MinGW 20260922 的 clang 23。

完整构建、6次编译、0警告、35套件和78个实际命令记录保存在本地 `artifacts/driver/green_review_fixes_root_01/manifest.json`，各次失败亦保留本地。Git 中的二进制文件不代替这些执行证明，也不表示真实 dev/final 输入、环境收据、A/A 或参数选择已经完成。生产入口继续读取原始冻结 manifest 和侧车完整性绑定。

数据集、运行时、临时缓存及完整原始执行归档仍被 Git 忽略。三个快照总计约7 MB；其他编译产物不纳入版本管理。
