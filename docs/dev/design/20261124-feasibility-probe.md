# P0 可行性探针

> **Status**: Draft · **Date**: 2026-11-24
> **Relates to**: [roadmap.md](../roadmap.md) P0、[ADR 0001](../adr/0001-on-time-archive-as-primary-source.md)、
> [data-sources.md](../requirements/data-sources.md) §2–§3、[business-objectives.md](../requirements/business-objectives.md) §3

## 1. 问题

[roadmap.md](../roadmap.md) 的 P0 要证明：准点存档能撑起“单个班次的准点概率”。
[ADR 0001](../adr/0001-on-time-archive-as-primary-source.md) 因此还是 Proposed。

现有证据只有一天、一条线（D19，2026-11-18）：114 班里只有 37 班有记录。
缺班如果和天气、时段有关，概率就会有系统偏差，这决定项目能不能做。

本篇在跑数据之前登记：测哪些指标、怎么测、门槛是多少、不通过怎么办。

## 2. 方案

### 2.1 做法

- 每个指标写四件事：问题、测法、门槛、结论写到哪。
- 数字分两级标记：
  - **源实测**：直接查询上游得到，如 `count(*)`、某字段有没有值；
  - **指标实测**：经本项目联结、清洗之后算出，如覆盖率、联结率。
  报数字时注明是哪一级。
- 只读上游，不建管道。探针脚本放 `probe/`，执行时补进仓库，入口命令随结果一起记录。
- 限时 3 个工作日。到时没测完的硬门槛项记为“未知”，按不通过处理。

### 2.2 样本

只看工作日（`Day Type = Weekday`）。

- **窗口 A（秋季，全网）**：最近一期表 `gp3k-am4u` 的全部记录，2026-10-10 至 2026-11-23，
  73 条线路。当前 GTFS 有效期 2026-09-06 至 2026-12-12，覆盖整个窗口，不需要历史 GTFS。
- **窗口 B（冬季）**：存档 2025-12 至 2026-03 四个月。需要那一时期的 GTFS，
  能否拿到由 G3 回答。G2 的天气对比主要靠这个窗口。

```bash
# 窗口 A：一次导出全部记录（约 513 万行）
curl -L -o otp_recent.csv "https://data.winnipeg.ca/api/views/gp3k-am4u/rows.csv?accessType=DOWNLOAD"
# 窗口 B：月度压缩包的下载地址
curl -s "https://data.winnipeg.ca/resource/cymk-nyei.json?\$select=start_date,url,size&\$where=start_date%3E='2025-12-01'%20and%20start_date%3C'2026-04-01'&\$order=start_date"
# 当前 GTFS
curl -L -o google_transit.zip https://gtfs.winnipegtransit.com/google_transit.zip
```

### 2.3 恶劣天气日的定义（登记）

工作日满足任一条即为恶劣天气日：

- **降雪日**：Open-Meteo 历史天气（archive API，温尼伯市中心 49.895, −97.138）日降雪量
  `snowfall_sum` ≥ 5 cm。这是再分析模型的格点值，不是站点观测；选它是因为 ECCC 日数据没有降雪量（见 §4）。
- **极寒日**：ECCC `WINNIPEG INTL A`（`5023227`）观测的日最低温 ≤ −30 °C。
- **冻雨日**：逐时观测的天气描述含冻雨。逐时数据能否拿到在执行时确认；拿不到就从定义里去掉这一条，
  并在结果里写明。

```bash
curl -s "https://archive-api.open-meteo.com/v1/archive?latitude=49.895&longitude=-97.138&start_date=2025-07-01&end_date=2026-11-23&daily=snowfall_sum,precipitation_sum,temperature_2m_min&timezone=America/Winnipeg"
curl -s "https://api.weather.gc.ca/collections/climate-daily/items?f=json&limit=1000&CLIMATE_IDENTIFIER=5023227&datetime=2025-07-01/2026-11-23"
```

### 2.4 硬门槛：决定 Go / No-Go

#### G1 班次覆盖率

- **问题**：每天实际出现的班次占时刻表班次的多少。
- **测法**：按 [data-sources.md](../requirements/data-sources.md) §2 的键（站点 + 计划时间）联结出 `trip_id`。
  时刻表班次 = 当天生效的 `service_id`（`calendar.txt` 加 `calendar_dates.txt` 例外）下该线路的班次数。
  - 覆盖率 = 至少有一条记录的班次数 ÷ 时刻表班次数，按（日期，线路）算。
  - 站点完整度 = 出现的班次里，有记录的站数 ÷ 时刻表站数。
  - 样本：窗口 A。
- **门槛**：至少 3 条线路在窗口 A 工作日的覆盖率中位数 ≥ 30%，
  且这些线路上出现班次的站点完整度中位数 ≥ 90%。
  MVP 的线路从达标的线路里选；D19 不达标就不保留。
- **结论写到**：[data-sources.md](../requirements/data-sources.md) §3，扩成多天、全网的读数。

#### G2 缺失是否随机

- **问题**：缺班是否和会影响晚点的条件有关。若恶劣天气日缺得更多，模型会系统性地低估雪天晚点。
- **测法**：
  - **a. 天气**：窗口 B 里，同一线路恶劣天气日和其余工作日的覆盖率之差，
    以天为单位做自助法，给出 95% 区间。
  - **b. 时段**：早高峰（6–9 时）、日间（9–15 时）、晚高峰（15–18 时）、晚间（18 时后）
    四段的覆盖率。样本：窗口 A。
  - **c. 机制**：缺失是否按 GTFS 的 `block_id` 成片，即同一车次链当天整条都缺或整条都有的比例。
    成片缺失说明多半是部分车辆没上报，与晚点无关。
- **门槛**：
  - a：差值的绝对值 < 5 个百分点，且 95% 区间落在 ±10 个百分点以内；
  - b：四个时段覆盖率的极差 < 15 个百分点；
  - c 只记录，用来解释 a、b 的结果，不设门槛。
- **依赖**：a 需要窗口 B 的 GTFS。G3 拿不到时改用窗口 A 里的恶劣天气日，
  天数不足 5 天则 a 记为“未知”。
- **结论写到**：[data-sources.md](../requirements/data-sources.md) §3。

#### G3 历史 GTFS 与联结率

- **问题**：2025-07 线网改造之后各期的记录能不能逐期对上班次。
- **测法**：
  - 列出 2025-07 以来各期 GTFS 的可得来源（如 Mobility Database、Transitland）及其有效日期；
  - 每期 GTFS 对相应月份的存档做联结。联结率 = 匹配上的工作日行数 ÷ 工作日总行数，
    同时报重复键的比例。
- **门槛**：2025-07-01 以来的工作日里，有对应 GTFS 的天数 ≥ 90%；
  每个有 GTFS 的月份，联结率 ≥ 95%。
- **结论写到**：[data-sources.md](../requirements/data-sources.md) §2。

#### G4 恶劣天气日样本量

- **问题**：改造之后的数据够不够检验“恶劣天气日明显好于基线”这个假设
  （[business-objectives.md](../requirements/business-objectives.md) §3）。
- **测法**：用 §2.3 的定义，数 2025-07-01 至 2026-11-23 之间有准点记录的工作日里有多少个恶劣天气日。
  2026-10-01 至 2026-10-09 两张表都没有覆盖（见 §4），不计入。
- **门槛**：≥ 15 天。
- **结论写到**：[data-sources.md](../requirements/data-sources.md) §4。

### 2.5 只记录、不设门槛的项

结果写进 [data-sources.md](../requirements/data-sources.md) 或 MVP 设计文档的约束一节。

- **I1 数据质量**（窗口 A）：重复键比例；偏差绝对值 > 3,600 秒的比例；坐标落在城市范围外的比例。
- **I2 信号强度**（窗口 B）：
  - 恶劣天气日和其余工作日的偏差分布：中位数、P90 晚点、晚点超过 300 秒的比例；
  - 基线的 Brier score：用 2025-12 至 2026-02 估计同线路、站点、时段的历史频率，
    在 2026-03 上评分，事件为“晚点超过 300 秒”。
  分布几乎没有差别，就说明模型能学的东西很少，要在 MVP 设计里正视。
- **I3 标签效度**：终点站，以及计划停站 ≥ 2 分钟的站点（GTFS `arrival_time` 与
  `departure_time` 之差），在记录行数里的占比。这些站的离站偏差最不能代表到站。
- **I4 技术体量**：111 个月度压缩包的总大小（源实测）；抽一个月测解压后大小、读取加联结的耗时，
  外推全量回填的耗时。
- **I5 外部因素可得性**：[data-sources.md](../requirements/data-sources.md) §4 的 MVP 候选逐项确认
  历史覆盖的起止日期，以及前一天晚上能不能拿到。天气预报存档（如 Open-Meteo）能否覆盖窗口 B。
- **I6 许可**：City of Winnipeg 开放数据许可和 GTFS feed 的许可条款，是否允许公开展示由它们派生的数据和结果。

### 2.6 判定规则

| 结果 | 结论 | 后续 |
|---|---|---|
| G1–G4 全部通过 | Go | ADR 0001 追加更正块改为 Accepted；按 G1 的结果选 MVP 线路 |
| G1 或 G2 不通过 | 转向 | 走 [roadmap.md](../roadmap.md) P0 的两条出路之一，先写 ADR |
| G3 不通过，其余通过 | 有条件 Go | 训练窗口缩到有 GTFS 的时期，写 ADR 说明 |
| 只有 G4 不通过 | Go | 恶劣天气日的假设从检验降为描述，写进局限；MVP 的通过门槛不受影响 |

### 2.7 结果写到哪

本篇写完冻结，不回填结果。实测数字按三件套（测量时间、命令、环境）写进
[data-sources.md](../requirements/data-sources.md)；Go / No-Go 写成 ADR 0001 的更正块，
转向时另写新 ADR。P0 不上线任何东西，不写 `launch/`。

## 3. 被否决的方案

- **先建全量回填管道，再看覆盖率**：把成本最大的一步放在最大的风险之前。
- **只看月度行数的断层来判断覆盖**：分不清是班次真的减少了还是采集缺失了，
  见 [data-sources.md](../requirements/data-sources.md) §1.2。
- **随机抽少数几天**：窗口 A 全网 45 天约 513 万行，一次导出就能拿全，没有必要抽样。
- **正式的缺失机制检验（如 Little's MCAR test）**：缺失的单位是整个班次，缺的班次没有任何观测值，
  检验的前提不成立。改用可观测条件下的覆盖率对比。
- **竞品调研、用户访谈、实时 API key**：不影响 MVP 能不能做，不进 P0。
- **用 ECCC 降水量加温度近似降雪**（日降水 ≥ 5 mm 且最高温 ≤ 0 °C）：只有一个站有降水量，
  而且是间接推算；Open-Meteo 直接给出日降雪量，历史和预报两边口径一致。

## 4. 约束与假设

- **ECCC 日数据没有降雪量**：2026-11-24 查 GeoMet `climate-daily`，温尼伯一带（bbox −97.5,49.7,−96.8,50.1）
  的所有站点在 2026-01 的 `TOTAL_SNOW` 都为空；只有 `WINNIPEG A CS`（`502S001`）有日降水量和积雪深度，
  `WINNIPEG INTL A`（`5023227`）只有温度。源实测。
  ```bash
  curl -s "https://api.weather.gc.ca/collections/climate-daily/items?f=json&limit=5000&bbox=-97.5,49.7,-96.8,50.1&datetime=2026-01-01/2026-01-31"
  ```
  因此降雪改用 Open-Meteo archive API：2026-11-24 查 2025-07-01 至 2026-11-23 共 511 天，
  `snowfall_sum`、`precipitation_sum`、`temperature_2m_min` 全部有值。源实测（只查了有没有值，
  没有数降雪日，免得在登记门槛前看到 G4 的结果）。它是模型值，与真实降雪有误差，
  在结果里作为局限写明。Open-Meteo 的历史预报接口（historical-forecast API）也能返回
  同一字段，I5 用它确认“前一天能拿到的预报”。
- **登记门槛之前已经看到的数字**：`5023227` 在 2025-11-01 至 2026-03-31 期间有 5 天最低温 ≤ −30 °C
  （全部日子，没有区分工作日）。G4 的门槛是在知道这个数的情况下定的，如实记下。
- **2026-10-01 至 10-09 没有覆盖**：存档 `cymk-nyei` 最新一期是 2026-09，
  最近一期表从 2026-10-10 开始。源实测，2026-11-24。
- **假设当前 GTFS 有效期内没有中途改班**，例外日期已在 `calendar_dates.txt` 里体现。
- **窗口 A 是秋季，恶劣天气日少**：G2a 依赖窗口 B，也就依赖 G3。G3 不通过时 G2a 可能只能记为“未知”，
  按 §2.1 的规则按不通过处理。

## 5. 判据

本次探针做完的标志：

- G1–G4 每一项都有数字，或者明确标为“未知”并写明原因；
- 数字带三件套写进 [data-sources.md](../requirements/data-sources.md)，并标明是源实测还是指标实测；
- 按 §2.6 给出 Go / 转向 / 有条件 Go 的结论，并更新 ADR 0001。
