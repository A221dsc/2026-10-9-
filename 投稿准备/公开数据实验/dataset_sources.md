# 公开数据来源、采集规则与认可依据

核验日期：2026-10-05。当前主方案为官方 NYC TLC 2024-01 完整日历月的 pickup 时间戳投影，2024-02 为预先指定的独立月份验证。两月均来自同一机构、同一年度表，属于时间外推验证，不能描述成两个独立数据来源。SOSD wiki 保留为另一个来源的候选；本轮不使用分块抽样制造热点，不下载其完整大文件。

## 主数据：NYC TLC Yellow Taxi 2024 年官方表

- [TLC 官方下载与说明](https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page)：记录由获授权的技术提供商提交，包含上下车日期时间等字段，TLC 不保证全部记录准确。
- [NYC Open Data 官方 2024 Yellow Taxi Trip Data](https://data.cityofnewyork.us/Transportation/2024-Yellow-Taxi-Trip-Data/rwwi-khbc)：发布者为 TLC，每行一车程，19 列；`tpep_pickup_datetime` 表示计价器开始计时的日期时间，类型为 Floating Timestamp。该页面许可明确为 **unspecified**，不可写成 CC0。
- [官方 Yellow Taxi 数据字典](https://www.nyc.gov/assets/tlc/downloads/pdf/data_dictionary_trip_records_yellow.pdf)。2025 年起增加拥堵费列，本方案固定 2024 年 schema。
- [AWS Open Data Registry 对 TLC 的登记](https://registry.opendata.aws/nyc-tlc-trip-records-pds/)提供数据管理者、引用格式，并将许可指向 [NYC Terms of Use](https://www.nyc.gov/main/terms-of-use)。登记与机构发布是来源可信度依据，不是把该数据称为学界统一索引 benchmark 的依据。

官方月 Parquet 链接为 [2024-01 Yellow](https://d37ci6vzurychx.cloudfront.net/trip-data/yellow_tripdata_2024-01.parquet) 和 [2024-02 Yellow](https://d37ci6vzurychx.cloudfront.net/trip-data/yellow_tripdata_2024-02.parquet)。本机访问 CloudFront 被连接重置，未核验这些文件的实际字节数、物理 Parquet schema 或排序。最终采用 **同机构官方年度表的日历月筛选**，不是声称已下载这些 Parquet 文件的每一物理行。

## 完整月份投影与无损编码

API 为 `https://data.cityofnewyork.us/resource/rwwi-khbc.csv`。投影仅 `tpep_pickup_datetime`，Jan 固定条件为 `>= '2024-01-01T00:00:00' AND < '2024-02-01T00:00:00'`；Feb 为相应二月到三月边界。该规则定义完整日历月，排除不落在该月的原年度表记录及 null，没有按桶占用、重复程度或性能筛选记录。

每页显式 `$order=:id`、`$limit`、`$offset`。Socrata 的[官方排序文档](https://dev.socrata.com/docs/queries/order.html)明确指出未指定排序不能保证分页稳定，并推荐至少 `$order=:id`。[官方 LIMIT 文档](https://dev.socrata.com/docs/queries/limit.html)说明接口版本的上限；采集器以实际返回行数推进 offset，保留每页 URL、UTC、返回行数和响应 SHA256。

原 CSV 保留原生字符串值；只删除分页重复表头并按同一来源排序连接。索引用 id 为该完整投影的数组位置加一，未伪称它是原始车程业务 id。官方 source `:id` 字符串不投影，来源行序由显式排序及冻结 CSV 保存。

[Floating Timestamp 官方类型说明](https://dev.socrata.com/docs/datatypes/floating_timestamp.html)规定毫秒精度且不含时区，返回格式会带毫秒。采集器全量检查小数；仅当每一条均为整秒时，才写 month_start 起算的整数秒，**没有舍入**。若存在非零毫秒，必须保留毫秒并另报单位。转换采用不附带时区的 civil-time 算术，不把该类型冒称 UTC 时刻。

最终二进制文件为 `data/tlc_2024_01_uint64.bin` 与 `data/tlc_2024_02_uint64.bin`：8 字节小端 uint64 行数，之后每行 8 字节小端 uint64 相对秒，保持来源 `:id` 顺序；id=位置+1，stride=行数+1，span=该月天数×86400。实际文件名称、精度、SHA256、min/max、重复比例及相邻下降次数以 [manifest.json](./data/manifest.json) 为准。

Jan 的前置官方聚合返回 2,964,617 行、1,575,694 个 distinct 原生时间戳，首尾为 `2024-01-01T00:00:00.000` 与 `2024-01-31T23:59:55.000`。重复额外记录占比定义为 `1-distinct/N`，约 46.85%；这是原生时间戳重复，未对秒或分钟作聚合。完整下载后必须再次核对 count、distinct、min/max 及源表版本。

精确 Jan 聚合 URL：

[官方 Jan count/distinct/min/max](https://data.cityofnewyork.us/resource/rwwi-khbc.json?%24select=count%28%2A%29+as+rows%2Ccount%28distinct+tpep_pickup_datetime%29+as+distinct_timestamps%2Cmin%28tpep_pickup_datetime%29+as+first_time%2Cmax%28tpep_pickup_datetime%29+as+last_time&%24where=tpep_pickup_datetime+%3E%3D+%272024-01-01T00%3A00%3A00%27+AND+tpep_pickup_datetime+%3C+%272024-02-01T00%3A00%3A00%27)

固定三行的来源排序核验返回 `00:57:55`、`00:03:00`、`00:17:06`，已说明该官方投影顺序不是 chronological。完整数据的下降计数会在 manifest 中报告。即使另行按时间排序，也应称为“按 event time 排序的重放”；不能称作观察到的真实到达流。

### 两月已完成的下载校验

2024-01 全量下载 2,964,617 行，与官方聚合的 count、distinct、min/max 完全一致；源表版本及聚合在下载前后未变化。所有原生毫秒小数均为 `.000`，整数秒编码无损。原 `:id` 顺序有 1,290,557 次相邻时间下降，不能描述成时间递增到达流。

- 原 CSV：77,080,065 字节；SHA256=`78f7753fb6656e08273bd62664ba1b9dbbf10def71146ba3efdbeb90e42c8f6b`。
- 最终二进制：23,716,944 字节；SHA256=`070d1574bf455dce54daad47a64ecda9176bc6cd1af771d84d8b0c3de1b0da7d`；`n=2964617, stride=2964618, span=2678400, min_key=0, max_key=2678395`。
- Jan 独立冻结审计文件为 `data/manifest_2024_01.json`；两月最终统一审计文件为 `data/manifest.json`，包含每页精确 URL、UTC、行数和响应 SHA256。

2024-02 同样全量下载并通过下载前后官方 count、distinct、min/max 和源表版本校验。原生时间戳为 `2024-02-01T00:00:00.000` 至 `2024-02-29T23:59:58.000`；全部毫秒小数均为 `.000`，没有舍入、去重、人工增加重复或改变来源行序。

| 指标 | 2024-01 主实验 | 2024-02 月份外验证 |
| --- | ---: | ---: |
| 完整下载行数 | 2,964,617 | 3,007,533 |
| 原生时间戳 distinct 数 | 1,575,694 | 1,531,278 |
| 原生重复额外记录数 | 1,388,923 | 1,476,255 |
| 重复额外记录占比 `1-distinct/N` | 46.8500% | 49.0852% |
| 原 `:id` 顺序的相邻下降次数 | 1,290,557 | 1,318,984 |
| 相对秒 min / max | 0 / 2,678,395 | 0 / 2,505,598 |
| span（秒） | 2,678,400 | 2,505,600 |
| stride | 2,964,618 | 3,007,534 |
| CSV 字节 | 77,080,065 | 78,195,881 |
| 二进制字节（含数量头） | 23,716,944 | 24,060,272 |

Feb 原 CSV SHA256=`c7ff193a825c82c7bda296dd6fe35a263ea4b5cb52d49221148a50debce07cf7`；最终 `data/tlc_2024_02_uint64.bin` SHA256=`2d41927f3f1e7e7869454b98b3c4779d42553bec28424a25317126c60e71e29c`。Jan 下载 UTC 为 `2026-10-05T13:58:58+00:00` 至 `2026-10-05T14:08:02+00:00`；Feb 为 `2026-10-05T14:08:08+00:00` 至 `2026-10-05T14:17:12+00:00`；每批及最终时间以 manifest 为准。两份最终相对秒二进制分别于 `2026-10-05T14:18:15+00:00` 和 `2026-10-05T14:18:16+00:00` 写成。数据处理全部退出后才进行正式计时。

精确 Feb 聚合链接为 [官方 Feb count/distinct/min/max](https://data.cityofnewyork.us/resource/rwwi-khbc.json?%24select=count%28%2A%29+as+rows%2Ccount%28distinct+tpep_pickup_datetime%29+as+distinct_timestamps%2Cmin%28tpep_pickup_datetime%29+as+first_time%2Cmax%28tpep_pickup_datetime%29+as+last_time&%24where=tpep_pickup_datetime+%3E%3D+%272024-02-01T00%3A00%3A00%27+AND+tpep_pickup_datetime+%3C+%272024-03-01T00%3A00%3A00%27)。两月还分别核验 `offset=N` 后返回无数据，避免把预期行数等同于实际完整下载。

## 第二来源候选：SOSD wiki / books

认可依据为作者的 [PVLDB《Benchmarking Learned Indexes》](https://vldb.org/pvldb/vol14/p1-marcus.pdf)及[官方 SOSD 仓库](https://github.com/learnedsystems/SOSD)。它是面向排序整数键的公开索引 benchmark；其数据不能自动提供真实请求轨迹或原始事件到达次序。[2019 原始论文](https://mlforsystems.org/assets/papers/neurips2019/sosd_kipf_2019.pdf)说明 books/amzn 来自图书销售流行度数据，wiki 来自 Wikipedia 编辑时间戳。当前官方数据为排序的 uint32/uint64 标量。

来源及格式：

- [官方 scripts/download.sh](https://raw.githubusercontent.com/learnedsystems/SOSD/master/scripts/download.sh)下载压缩的 wiki 200M、books 800M 等。wiki 完整解压文件 MD5=`4f1402b1c476d67f77d2da4955432f7d`，books 800M MD5=`8708eb3e1757640ba18dcd3a0dbb53bc`。
- [wiki 官方 Harvard 数据访问 URL](https://dataverse.harvard.edu/api/access/datafile/:persistentId?persistentId=doi:10.7910/DVN/JGVF9A/SVN8PI)；[books 官方 Dropbox URL](https://www.dropbox.com/s/y2u3nbanbnbmg7n/books_800M_uint64.zst?dl=1)。Harvard 页面本次浏览遇到机器人验证，不从未读到的元数据推定许可。
- [官方 downsample.py](https://raw.githubusercontent.com/learnedsystems/SOSD/master/downsample.py)用 books 800M 的每 4 条取一生成 books 200M；不是现成 ≤100MB 的官方小文件。[util.h](https://raw.githubusercontent.com/learnedsystems/SOSD/master/util.h)采用 8 字节 uint64 数量头，随后保存标量键。
- [Zenodo DOI 10.5281/zenodo.15240501](https://zenodo.org/records/15240501)由 Lorenzo Bellomo 上传，提供未压缩镜像。其 [API 元数据](https://zenodo.org/api/records/15240501)声明 `cc-by-4.0`；wiki 文件声明 MD5 与 SOSD 官方值一致。它是有出处的镜像，不是 SOSD 作者的下载服务器。仓库 GPL-3.0 是软件许可证，不冒称数据统一许可。

已验证 [Zenodo wiki 原始二进制内容端点](https://zenodo.org/api/records/15240501/files/wiki_ts_200M_uint64/content)支持 HTTP Range。只请求 `bytes=0-15` 返回 206，`Content-Range: bytes 0-15/1600000008`，小端数量头为 200,000,000。整文件未下载，因此未自行验证完整 MD5。books 800M 大小为 6,400,000,008 字节，镜像 books 50M 仍为 400,000,008 字节；没有发现符合 ≤100MB 条件的标准 books/wiki 小文件。

压缩 `.zst` 的任意字节 Range 不是解压后任意 rank 的访问。未压缩镜像可以读 rank `i` 的字节 `8+8*i ... 8+8*i+7`，但连续 rank 窗口会人为制造聚簇。不得以 32 个连续窗口充当原分布主验证。后续若采用 SOSD 小样本，应预先固定全局均匀 rank 抽样或系统等步长抽样，披露采样与下载方法，保留原键值及重复，不制造重复、不按性能或大桶挑选；允许该来源出现无收益的边界结果。

## 实验解释边界

真实时间戳/整数键不等于真实数据库请求。后续随机删除、热点移动或范围访问若由实验生成，应标为“真实存储数据上的控制请求实验”。键值不能为了适配固定目录而四舍五入到分钟或小时；使用日历月跨度直接计算 4096 个桶，不改变时间戳相等关系。Jan 参数与策略冻结后在 Feb 验证，不依据 Feb 结果修改主策略。
