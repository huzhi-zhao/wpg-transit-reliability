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
| [0001](0001-on-time-archive-as-primary-source.md) | 主数据源选公交准点存档 | 数据源 | Accepted（P0 通过后） | 2026-11-24 |
| [0002](0002-trip-reliability-not-realtime-eta.md) | 产品回答“这一班多靠得住”，不做实时到站 | 范围 | Accepted | 2026-11-24 |
| [0003](0003-features-known-the-day-before.md) | 特征只用前一天已知的信息，311 不进 v1 | 口径 | Accepted | 2026-11-24 |
| [0004](0004-mvp-trips-departing-before-1800.md) | MVP 只做首站 18:00 前发车的班次 | 范围 | Accepted（口径由 0005 修改） | 2026-11-24 |
| [0005](0005-mvp-on-time-records-only.md) | MVP 只用准点数据集，不还原班次、不接外部数据 | 范围 | Accepted（范围由 0007 收窄，外部数据由 0008 部分放开） | 2026-11-25 |
| [0006](0006-mvp-follows-crisp-dm.md) | MVP 按 CRISP-DM 六个阶段组织 | 方法论 | Accepted（交付清单由 0007 收缩） | 2026-11-27 |
| [0007](0007-mvp-one-route-direction.md) | MVP 收缩到一条线路的一个方向，目标是练出并评估一个模型 | 范围 | Accepted | 2026-11-27 |
| [0008](0008-mvp-small-side-tables.md) | MVP 接入四个外部来源的小表，在数据准备阶段合并 | 范围 | Accepted | 2026-11-27 |
