# Architecture Decision Records

一个 ADR 记录一个决策：**背景 → 决策 → 被否决的方案 → 后果**。

规则：

- ADR 不改名、不删除。决策过时了就写一篇新的，把旧的标为 `Superseded by NNNN`。
- 编号连续递增，四位数，文件名 `NNNN-kebab-case-title.md`。
- 每篇顶部必须有 `Status` 和 `Date`。
- 新增 ADR 后在下表登记。

ADR 不限于技术选型：口径决策（哪个字段代表什么）、范围决策、方法论决策同样算。
判据只有一条：**后面的人要踩着它走，改它要付代价**。

| # | 标题 | 类别 | 状态 | 日期 |
|---|---|---|---|---|
| [0001](0001-on-time-archive-as-primary-source.md) | 主数据源选公交准点存档 | 数据源 | Proposed（待 P0） | 2026-11-24 |
| [0002](0002-trip-reliability-not-realtime-eta.md) | 产品回答“这一班多靠得住”，不做实时到站 | 范围 | Accepted | 2026-11-24 |
| [0003](0003-features-known-the-day-before.md) | 特征只用前一天已知的信息，311 不进 v1 | 口径 | Accepted | 2026-11-24 |
| [0004](0004-mvp-trips-departing-before-1800.md) | MVP 只做首站 18:00 前发车的班次 | 范围 | Accepted | 2026-11-24 |
