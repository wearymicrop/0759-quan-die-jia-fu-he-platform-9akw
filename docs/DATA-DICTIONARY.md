# 数据字典

## 流水 `events.jsonl`

文件编码为 UTF-8，可带 BOM，每个物理行一个对象。行号从 1 开始。销售与退货的业务主键各为 `type + id`，编号保留前导零，同键规范化后完全相同为重传，内容冲突时隔离全部版本。时间输入需有显式偏移，UTC 排序，交易日按 UTC+08:00 划分。

| 类型 | 字段 | 规则 |
|---|---|---|
| `sale` | `id`、`shop`、`at` | 销售编号、门店、交易时点 |
| `sale` | `lines` | 键为 `id`，包含 `category`、正整数 `qty` 和单价 `price` |
| `sale` | `coupons`、`paid` | 候选券号列表和小票实付 |
| `return` | `id`、`at`、`order`、`line` | 退单编号、退货时点、原单号、原明细号 |
| `return` | `qty`、`cash` | 退货件数和实际退款 |

金额输入为十进制字符串，支持人民币符号、规范千分位与全角数码，最多两位小数。输出金额均为整数分。

## 规则集 `rules.json`

`versions` 含 `code`、`version`、`start`、`end`、`group`、`kind`、`value`。生效区间采用 `[start, end)`。`fixed` 的 `value` 是金额串，`percent` 的 `value` 是减免比例基点，1000 表示减 10%。`minimum` 默认为 0，空 `shops` 和 `categories` 对所有门店或品类生效。`rank` 越小越先用券，同位按券号。`pairs` 是明确允许的无序券对。同组互斥优先。券号和版本号联合唯一，购买时命中多个版本则隔离该单。

门槛使用合格明细的原价小计。百分比用当时合格余额并四舍五入到分，任何券减免最多为当时余额。券内按比例用最大余数法分摊，余数并列按明细号。组合按实付、券数、字典序比较。

## 冲回和归档

同一原单明细按退货 UTC、退单号排序。把原行减免先均分到件，余分给前几件，按累计已退件数获取本次减免。跨日时沿用同一原单明细。现金不一致保留双方金额及差额。`source_line` 是流水行号，`rule_index` 是规则列表序号，`original_line` 是原购流水行号。清单保存规则版本与规范化输入摘要，归档附件包含全部模块证据。

## 退货结算复核单 `settlement`

按原票逐单输出，复核单 `id` 为批次输入摘要与原单号的 16 位哈希，同批次重算稳定。

| 字段 | 含义 |
|---|---|
| `original` | 原组合：入选券 `applied`、毛额、实摊优惠、复算实付与原实付 |
| `lines` | 逐明细原件/已退/剩余件数，已退款、剩余净额与结构差 `gap`（0 即对平） |
| `returns` | 已过账退货：商品额、冲减优惠、应退、实退、现金差，按原票按件口径 |
| `blocked_returns` | 阻断退货（超件、缺行、早于原购等），留痕但不冲减 |
| `remaining` | 剩余篮按原票时点规则重判的券资格与候选组合；退空为 `basket_empty` |
| `coupon_carry` | 原组合各券在剩余篮的资格结论与合格基数 |
| `differences` | 差异来源：`RETURN_CASH_GAP`（可发布）与 `COUPON_THRESHOLD_DRIFT`（仅解释） |
| `blocking` / `publishable` | 硬阻断明细（`LINE_IMBALANCE`、`SALE_ISOLATED`、`RETURN_CLAIM_BLOCKED`）与发布结论 |
| `orphan_returns` | 缺原票退货，单独留痕，不并入任何复核单 |

发布接口 `POST /api/runs/{id}/settlements/{sheet}/publish` 在独立 `settlements` 表同键去重，重试返回 `reused=true` 且不重复冲减；硬阻断返回 `SETTLEMENT_NOT_PUBLISHABLE`（422）。
