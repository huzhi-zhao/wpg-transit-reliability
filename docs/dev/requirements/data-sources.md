# 数据源

> 本篇所有数字均于 **2026-11-24** 对 City of Winnipeg 开放数据门户
> （`data.winnipeg.ca`，Socrata SODA API，实时）和 Winnipeg Transit 公开的 GTFS 测得，
> 命令见各节。上游会变，引用前看测量时间。

## 1. 主数据源：Transit On-Time Performance

门户上有两张表：

- **存档** `cymk-nyei`：每行是一个月度压缩包的元数据（起止日期、行数、大小、下载地址）。
  - 111 个月度文件，2017-07 至 2026-09，**行数合计 625,468,342**。
  - 单月压缩包 80 到 204 MB。
- **最近一期** `gp3k-am4u`：5,130,584 行，覆盖 2026-10-10 至 2026-11-23，
  73 条线路、3,885 个站点。每天更新。

```bash
curl -s "https://data.winnipeg.ca/resource/cymk-nyei.json?\$select=sum(rows),min(start_date),max(end_date)"
curl -s "https://data.winnipeg.ca/resource/gp3k-am4u.json?\$select=min(scheduled_time),max(scheduled_time),count(distinct%20route_number),count(distinct%20stop_number)"
```

### 1.1 字段

存档 CSV 的表头，2017-07 与 2026-09 两个文件一致（读压缩包头部实测）：

- `Row ID`：自增编号
- `Stop Number`：站点编号，对应 GTFS `stop_id`
- `Route Number`：线路编号。改造前是 `15` 这类数字，改造后是 `F7`、`D19` 这类编号
- `Route Name`：线路名
- `Route Destination`：终点方向，可替代方向字段
- `Day Type`：`Weekday` / `Saturday` / `Sunday`
- `Scheduled Time`：计划离站时间，精确到秒，本地时间
- `Deviation`：实际与计划的偏差，单位秒，**负数为晚点，正数为提前**（门户说明原文）
- `Location`：站点坐标，WKT `POINT`

一行 = 一辆车离开一个站点一次。门户说明：数据来自车载计算机和 GPS，
有少量传输缺失和 GPS 错误，按车载上报原样发布。

**没有的字段**：`trip_id`、车辆编号、方向编号、载客量、到站时间。

### 1.2 月度行数的断层

- 2017 至 2020 年：每月约 700 万至 870 万行。
- 2025-04：2,869,689 行（明显偏低，原因未查）。
- 2025-07 起：每月 235 万至 355 万行，约为早年的三分之一。

线路编号在同一时期换了体系，说明 2025 年中有一次线网改造。
行数下降是改造后班次和站点减少，还是采集覆盖缩小，**尚未区分**；
在区分之前，改造前后的准点率不能直接比较。

```bash
curl -s "https://data.winnipeg.ca/resource/cymk-nyei.json?\$select=start_date,rows&\$order=start_date&\$limit=200"
```

## 2. 班次重建：与 GTFS 联结

时刻表：`https://gtfs.winnipegtransit.com/google_transit.zip`，
测量时的 feed 有效期为 2026-09-06 至 2026-12-12。`stop_times.txt` 有 `trip_id`、
`stop_id`、`departure_time`（精确到秒）、`stop_sequence`；`trips.txt` 有
`route_id`、`service_id`、`direction_id`、`block_id`。没有 `timepoint` 字段。

**D19 抽样（2026-11-18，周三）**：

- 当天 D19 存档记录 1,116 行，按（`Stop Number`，`Scheduled Time` 的时分秒）
  对 GTFS 的（`stop_id`，`departure_time`）联结，**全部匹配**。
- 同一键在当天出现重复 3 组（1,116 行，1,113 个不同键），需要清洗。
- D19 工作日（`service_id = 1`）时刻表共 114 班，每班 32 或 33 站。

结论：**改造后的记录可以靠时刻表还原 `trip_id` 和站序**。历史各期需要对应时期的 GTFS，
能否拿到是 P0 的检查项。

## 3. 缺班

同一天 D19 的 1,116 行只来自 **37 个班次**，时刻表上有 114 班。
出现的班次大约每站都有记录（1,116 / 37 ≈ 30 行每班）；缺的班次是整班缺失。

这与 §1.2 的行数断层可能是同一现象。若缺失与线路、时段或车辆相关
（例如只有部分车辆上报），概率估计会有系统偏差。**目前只有一天一条线的读数**，
P0 要扩大到多天、多线路。

D19 当天偏差分布：P5 = −245 秒，中位 = −45 秒，P95 = +97 秒；
提前超过 60 秒占 12.1%，晚点超过 300 秒占 3.2%。

```bash
curl -s "https://data.winnipeg.ca/resource/gp3k-am4u.json?\$select=stop_number,scheduled_time,deviation&\$where=route_number='D19'%20and%20scheduled_time%20between%20'2026-11-18T00:00:00'%20and%20'2026-11-18T23:59:59'&\$limit=50000"
```

## 4. 外部因素候选

准入规则：只用前一天已知的信息（[ADR 0003](../adr/0003-features-known-the-day-before.md)）。
“行数”列为 2026-11-24 的 `count(*)`；未写行数的尚未测。

**MVP 候选**

- **天气**：降雪量、冻雨、极寒、大雨。ECCC 日数据在温尼伯一带没有降雪量字段，
  降雪改用 Open-Meteo（历史用 archive API，2025-07-01 至 2026-11-23 的日降雪量全部有值，
  2026-11-24 测；前一天的预报用 historical-forecast API）。气温仍可用 ECCC 观测。
  训练用的历史值和预测时的预报值之间的差距需要处理。命令见
  [P0 可行性探针](../design/20261124-feasibility-probe.md) §2.3、§4。
- **冬季道路运营**：除雪状态（逐地址）`g3p4-h83y`、停车禁令 `mfzv-893p`。
- **施工和车道封闭** `h367-iifg`：每天更新。
- **日历**：节假日、中小学上课日、大学学期、大型活动（职业球赛等）。
- **客流（停站时间的代理）**：分站点上下车人数 `bv6q-du26`，2,405,173 行，
  按时刻表季度、时段平均，2017 年起。
- **拥挤**：满员拒载 `mer2-irmb`，203,082 行，2009-12 起。
- **铁路平交道口**：班次下游的平交道口数量，固定特征。道口位置来自 Transport Canada
  的道口清单（未测）；火车时刻不公开。
- **河水位和春汛封路** `tgrf-v2zc`：沿河道路的季节性封闭。

**实时修正阶段才用（次日拿不到）**

- 实时路段流量和车速 `bh78-7qpb`：1,465,467 行，2026-05-21 起，20 个站点，每 15 分钟。
- 固定计数站 `46sc-6jrs`：1,880,523 行，2019-12 起。MVP 只能用历史典型值。

**不采用**

- 311 服务请求：次日拿不到，只能用前一天的投诉量间接代表路况，与晚点的关系弱。
  见 [ADR 0003](../adr/0003-features-known-the-day-before.md)。

**拿不到**

- 取消班次、车辆故障、缺司机等运营内部信息：不公开。
