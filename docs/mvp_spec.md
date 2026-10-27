# MVP 实现说明（v0.5）

> 对应 README §12 P0。本文是首个版本的实现依据，可以直接交给编码 Agent 按顺序实现。凡与 README 冲突之处，以本文为准，并同步修正 README。

## 0. 目标与范围

### 0.1 MVP 要演示的完整流程

```
提问 → 必要时澄清 → 选择指标路径或 SQL 路径 → 执行 → 在界面展示结果、口径与条件 → 追问修改条件或引用上一轮结果
```

MVP 完成时应达到 README §12 验收标准的第 1 条：完整的产品演示可以在界面上连续运行。

### 0.2 范围

| 包含 | 不包含（P1 及以后） |
| --- | --- |
| 2 张宽表 + 1 张桥接表 | 合成干扰表、规模扩充 |
| 2 个指标：类目销售额、差评率 | 付款金额类指标、分摊规则 |
| 2 个维度（类目、客户州）+ 时间 | 卖家州等其他维度 |
| 指标路径与 SQL 路径 | 混合检索、示例库、反馈闭环 |
| 护栏：只读、单条 SELECT、函数白名单、LIMIT、超时 | 执行计划检查、RLS |
| `confirmed_context`：更新操作、持久化、指代、比较基准 | 上下文压缩、缓存 |
| `/tasks`、`/events`、`/reply`、`/sessions` | 幂等、续传、取消、反馈接口 |
| Streamlit 演示界面：对话、条件面板、结果与 SQL | 界面上的取消、重连、历史与反馈 |
| API 模型 + 小模型推理端点 | SFT、RL |
| 约 20 道开发题、约 6 组多轮对话、冻结测试集 | 鲁棒性集、安全集、回归门禁 |

### 0.3 配置项（`.env`）

| 名称 | 默认值 | 说明 |
| --- | --- | --- |
| `REFERENCE_DATE` | 由数据画像确定（§1.3） | 所有相对时间的基准日期 |
| `MAX_TURNS` | 8 | 单个任务的最大 act ⇄ tools 轮数 |
| `MAX_SQL_REPAIR` | 3 | SQL 路径中连续修复的最大次数 |
| `STATEMENT_TIMEOUT_MS` | 5000 | 单条查询超时 |
| `ROW_LIMIT` | 1000 | 自动追加的 LIMIT 上限 |
| `RESULT_PREVIEW_ROWS` | 20 | 返回给模型的结果预览行数 |
| `MODEL_ENDPOINT` / `MODEL_NAME` | — | 模型网关后端（API 模型或 vLLM） |
| `API_BASE_URL` | `http://localhost:8000` | 演示界面调用的 API 地址 |

## 1. 数据导入与数据画像

### 1.1 导入

将 Olist 原始 CSV 导入 `ods` schema（不导入地理位置表）：

| 表 | 来源文件 |
| --- | --- |
| `ods.orders` | `olist_orders_dataset.csv` |
| `ods.order_items` | `olist_order_items_dataset.csv` |
| `ods.order_payments` | `olist_order_payments_dataset.csv`（MVP 中不进入宽表） |
| `ods.order_reviews` | `olist_order_reviews_dataset.csv` |
| `ods.customers` | `olist_customers_dataset.csv` |
| `ods.products` | `olist_products_dataset.csv` |
| `ods.sellers` | `olist_sellers_dataset.csv` |
| `ods.category_translation` | `product_category_name_translation.csv` |

### 1.2 数据画像（`data/profile_olist.py`）

宽表设计依赖以下假设。**每一条都必须用画像验证**，结果写入 `docs/data_profile.md`；任何一条不成立，先修改宽表设计再继续。

| 编号 | 检查项 | 期望 / 处理方式 |
| --- | --- | --- |
| P1 | `orders.order_id` 唯一 | 期望唯一 |
| P2 | `order_items (order_id, order_item_id)` 唯一 | 期望唯一 |
| P3 | `customers.customer_id` 唯一 | 期望唯一（注意 `customer_unique_id` 才代表同一位顾客，MVP 不使用） |
| P4 | `products.product_id` 唯一；`product_category_name` 的空值数 | 空值类目在宽表中记为 `unknown` |
| P5 | 类目翻译覆盖率：有商品但没有英文翻译的类目；翻译表的键是否唯一 | 无翻译时保留原始葡萄牙语名称；翻译表键不唯一会导致左关联扇出 |
| P6 | `order_reviews`：`review_id` 是否唯一；`(review_id, order_id)` 是否唯一；每笔订单的评价数分布；`review_score` 空值数 | 若 `(review_id, order_id)` 不唯一，按 `review_answer_timestamp` 保留最新一条，并记录去重数量 |
| P7 | `order_status` 的取值与数量 | 确认 `canceled`、`unavailable` 的确切取值，写入指标定义 |
| P8 | `order_purchase_timestamp` 的最小值、最大值与月度订单数 | 用于确定 `REFERENCE_DATE` |
| P9 | 参照完整性：明细的 `order_id` 都存在于订单表；订单的 `customer_id` 都存在于客户表；明细的 `product_id`、`seller_id` 都存在 | 不满足的记录数写入画像报告；同时计算 DWS 宽表的预期行数 |
| P10 | 没有任何明细的订单数，以及这些订单上的评价数 | 用于说明差评率按类目拆分时的覆盖范围（§3.2） |

### 1.3 `REFERENCE_DATE` 的确定规则

数据尾部的月份可能只有零星订单。规则如下：

1. 计算每个自然月的订单数（首末月之间缺失的月份记为 0）；
2. 从最后一个月往前找，第一个订单数不低于"其之前 6 个月订单数中位数"一半的月份，记为**最后一个完整月**；
3. `REFERENCE_DATE` = 最后一个完整月的**次月 1 日**。

因此"上个月"就是最后一个完整月；"本月"指 `REFERENCE_DATE` 所在月，数据不完整，按 §5 的 `OUT_OF_SCOPE` 处理。确定的日期写入 `.env` 与 `docs/data_profile.md`。

在真实 Olist 数据上按此规则得到的预期值为 `2018-09-01`，以画像脚本的实际输出为准。本文的时间示例均按这个日期计算。

## 2. 宽表（`data/warehouse/`、`semantic/models.yaml`）

只允许 N:1 关联；每张表构建后执行**行数断言与唯一键断言**，断言失败则构建失败。预期行数来自画像 P9 的结果。

### 2.1 `dws.order_item`

- **行粒度：** 一条订单明细；
- **唯一键：** `(order_id, order_item_id)`；
- **关联：** `order_items` →（N:1）`orders` →（N:1）`customers`；`order_items` →（N:1）`products` →（N:1，左关联）`category_translation`；`order_items` →（N:1）`sellers`。

```sql
CREATE TABLE dws.order_item AS
SELECT
    i.order_id,
    i.order_item_id,
    i.product_id,
    i.seller_id,
    o.customer_id,
    c.customer_state,
    s.seller_state,
    COALESCE(t.product_category_name_english,
             NULLIF(trim(p.product_category_name), ''),
             'unknown')                       AS category,
    o.order_status,
    o.order_purchase_timestamp       AS purchase_ts,
    o.order_delivered_customer_date  AS delivered_ts,
    i.price                          AS item_price,
    i.freight_value
FROM ods.order_items i
JOIN ods.orders o        ON o.order_id = i.order_id
JOIN ods.customers c     ON c.customer_id = o.customer_id
JOIN ods.sellers s       ON s.seller_id = i.seller_id
JOIN ods.products p      ON p.product_id = i.product_id
LEFT JOIN ods.category_translation t
       ON t.product_category_name = p.product_category_name;

ALTER TABLE dws.order_item ADD PRIMARY KEY (order_id, order_item_id);
```

**断言：** `COUNT(*) FROM dws.order_item` = 画像 P9 给出的 `expected_dws_order_item_rows`。

### 2.2 `dws.order_category`（桥接表）

- **行粒度：** 一笔订单中出现的一个类目；
- **唯一键：** `(order_id, category)`；
- **用途：** 把订单级的事实（评价）归属到类目。

```sql
CREATE TABLE dws.order_category AS
SELECT DISTINCT order_id, category
FROM dws.order_item;

ALTER TABLE dws.order_category ADD PRIMARY KEY (order_id, category);
```

### 2.3 `dws.review`

- **行粒度：** 一条评价；
- **唯一键：** `(review_id, order_id)`；
- **关联：** `order_reviews` →（N:1）`orders` →（N:1）`customers`。

先建立去重视图。即使画像显示没有重复，也保留这一步，用于防御后续数据：

```sql
CREATE OR REPLACE VIEW ods.order_reviews_dedup AS
SELECT DISTINCT ON (review_id, order_id) *
FROM ods.order_reviews
WHERE review_id IS NOT NULL AND order_id IS NOT NULL
ORDER BY review_id, order_id, review_answer_timestamp DESC NULLS LAST;

CREATE TABLE dws.review AS
SELECT
    r.review_id,
    r.order_id,
    r.review_score,
    r.review_creation_date AS review_created_ts,
    o.order_status,
    c.customer_state
FROM ods.order_reviews_dedup r
JOIN ods.orders o    ON o.order_id = r.order_id
JOIN ods.customers c ON c.customer_id = o.customer_id;

ALTER TABLE dws.review ADD PRIMARY KEY (review_id, order_id);
```

**断言：** `COUNT(*) FROM dws.review` = 画像 P9 给出的 `expected_dws_review_rows`。

### 2.4 `semantic/models.yaml`

```yaml
order_item:
  table: dws.order_item
  grain: 一条订单明细
  primary_key: [order_id, order_item_id]

order_category:
  table: dws.order_category
  grain: 一笔订单中的一个类目
  primary_key: [order_id, category]

review:
  table: dws.review
  grain: 一条评价
  primary_key: [review_id, order_id]
  joins:
    order_category:
      on: review.order_id = order_category.order_id
      cardinality: one_to_many     # 一笔订单可能有多个类目，会产生扇出，需要归属规则
```

## 3. 指标（`semantic/metrics.yaml`）

### 3.1 类目销售额 `category_sales`

| 项 | 规则 |
| --- | --- |
| 业务定义 | 订单明细的商品金额之和 |
| 来源 | `order_item`（明细粒度） |
| 聚合 | `SUM(item_price)`，可加 |
| 运费 | **不含**运费 `freight_value` |
| 订单状态 | 排除已取消与不可用的订单（确切取值以 P7 为准） |
| 时间字段 | `purchase_ts`（下单时间） |
| 兼容维度 | `category`、`customer_state` |
| 不支持 | 按付款金额统计、按卖家州拆分（MVP 中均返回 `INCOMPATIBLE`） |
| 口径说明文本 | "销售额按商品金额统计，不含运费，不含已取消和不可用的订单，按下单时间归属" |

```yaml
category_sales:
  label: 销售额
  synonyms: [商品销售额, 销售金额, 卖了多少钱]
  model: order_item
  type: sum
  expr: item_price
  filters:
    - "order_status NOT IN ('canceled', 'unavailable')"
  time_field: purchase_ts
  dimensions: [category, customer_state]
  description: 销售额按商品金额统计，不含运费，不含已取消和不可用的订单，按下单时间归属
```

### 3.2 差评率 `bad_review_rate`

| 项 | 规则 |
| --- | --- |
| 业务定义 | 有效评分中评分 ≤ 2 的评价所占比例 |
| 来源 | `review`（评价粒度） |
| 分子 | 评分 ≤ 2 的评价数 |
| 分母 | **评分非空**的评价数 |
| 空值 | 评分为空的评价既不进分子也不进分母 |
| 分母为 0 | 返回空值，并在答案中说明"该范围内没有有效评分" |
| 多条评价 | 同一笔订单的多条评价分别计数 |
| 订单状态 | 不排除（评价反映的是体验，包括取消订单的评价） |
| 时间字段 | `review_created_ts`（评价创建时间） |
| 兼容维度 | `customer_state`（直接）；`category`（经桥接表，见归属规则） |
| 归属规则（按类目） | 订单包含多个类目时，该订单的评价计入其包含的**每个**类目；因此各类目的分母之和可能大于评价总数，**各类目的数值不能相加或平均为总体差评率**；没有任何明细的订单的评价不计入任何类目（覆盖范围见 P10） |
| 汇总方式 | 每个分组分别计算分子、分母后再相除，不对比率求平均 |

```yaml
bad_review_rate:
  label: 差评率
  synonyms: [负面评价率, 差评比例]
  model: review
  type: ratio
  numerator: "COUNT(*) FILTER (WHERE review_score <= 2)"
  denominator: "COUNT(*) FILTER (WHERE review_score IS NOT NULL)"
  time_field: review_created_ts
  dimensions: [customer_state, category]
  dimension_paths:
    category:
      via: order_category
      attribution: each_category      # 订单的评价计入其包含的每个类目
      additive_across: false
  description: 有效评分中评分不高于 2 分的评价占比，按评价创建时间归属
```

**注意：** 两个指标的时间字段不同。同一个"上季度"，销售额按下单时间统计，差评率按评价创建时间统计，答案的口径说明中必须写明。

## 4. 维度与编译器

### 4.1 `semantic/dimensions.yaml`

```yaml
category:
  label: 类目
  values_from: dws.order_category.category
  note: 英文类目名；无翻译时保留原始名称；缺失时为 unknown

customer_state:
  label: 客户所在州
  values_from: dws.order_item.customer_state
```

### 4.2 兼容矩阵

| 指标 \ 维度 | `category` | `customer_state` | 时间（月 / 季） |
| --- | --- | --- | --- |
| `category_sales` | 直接 | 直接 | `purchase_ts` |
| `bad_review_rate` | 经桥接表，`each_category` 归属 | 直接 | `review_created_ts` |

### 4.3 结构化查询（`query_metric` 的输入）

```json
{
  "metric": "category_sales",
  "group_by": ["category"],
  "filters": {"customer_state": {"op": "in", "values": ["SP"]}},
  "time_range": {"start": "2018-04-01", "end": "2018-07-01"},
  "compare_to": {"start": "2018-01-01", "end": "2018-04-01"},
  "order_by": {"field": "delta", "dir": "asc"},
  "limit": 10
}
```

- MVP 中每次查询只有一个指标；
- 时间区间为左闭右开，`start` 含、`end` 不含；
- `time_range` 与 `compare_to` 只接受程序解析后的绝对日期（§6.3），模型不直接写日期；
- `order_by.field` 可取 `value`、`value_current`、`value_compare`、`delta`、`delta_pct`；"下降最多"对应 `delta` 升序，"增长最多"对应 `delta` 降序。

### 4.4 编译规则（`semantic/compiler.py`）

1. 校验指标存在、维度与筛选维度都在该指标的兼容列表中，否则返回 `INCOMPATIBLE`；
2. 校验筛选取值合法（类目、州是否存在于维度取值中），否则返回 `INVALID_VALUE`，由 Agent 向用户确认；
3. 求和类指标：`SUM(expr)`，附加指标自带的过滤条件；
4. 比率类指标：同时输出 `numerator`、`denominator`、`value = numerator / NULLIF(denominator, 0)`；
5. 存在 `compare_to` 时，用带 `FILTER` 的条件聚合在同一条 SQL 中分别计算两个时间段，外层再计算差值与变化率；
6. 经桥接表关联时，在返回结果中附带归属规则与 `additive_across: false` 标记；
7. 排序时加入维度列作为第二排序键，保证结果顺序确定；
8. 用 sqlglot 构建 SQL，不做字符串拼接；
9. 返回 `{sql, explanation, error_code?}`；编译器内部异常返回 `COMPILER_ERROR`，不得被调用方当作 `NOT_COVERED` 处理。

**编译结果示例**（类目销售额，圣保罗州，上季度对比再上一季度，按下降幅度排序）：

```sql
WITH t AS (
    SELECT
        category,
        SUM(item_price) FILTER (WHERE purchase_ts >= '2018-04-01' AND purchase_ts < '2018-07-01') AS value_current,
        SUM(item_price) FILTER (WHERE purchase_ts >= '2018-01-01' AND purchase_ts < '2018-04-01') AS value_compare
    FROM dws.order_item
    WHERE order_status NOT IN ('canceled', 'unavailable')
      AND customer_state IN ('SP')
      AND purchase_ts >= '2018-01-01' AND purchase_ts < '2018-07-01'
    GROUP BY category
)
SELECT category, value_current, value_compare,
       COALESCE(value_current, 0) - COALESCE(value_compare, 0) AS delta,
       (COALESCE(value_current, 0) - value_compare) / NULLIF(value_compare, 0) AS delta_pct
FROM t
ORDER BY delta ASC, category
LIMIT 10;
```

**编译结果示例**（差评率，按类目）：

```sql
SELECT
    oc.category,
    COUNT(*) FILTER (WHERE r.review_score <= 2)          AS numerator,
    COUNT(*) FILTER (WHERE r.review_score IS NOT NULL)   AS denominator,
    COUNT(*) FILTER (WHERE r.review_score <= 2)::numeric
        / NULLIF(COUNT(*) FILTER (WHERE r.review_score IS NOT NULL), 0) AS value
FROM dws.review r
JOIN dws.order_category oc ON oc.order_id = r.order_id
WHERE r.review_created_ts >= '2018-04-01' AND r.review_created_ts < '2018-07-01'
GROUP BY oc.category
ORDER BY value DESC NULLS LAST, oc.category
LIMIT 10;
```

## 5. 路由与回退分类（`agent/router.py`）

### 5.1 流程

1. 模型调用 `list_metrics` 后输出结构化意图：候选指标、分组维度、筛选条件、时间表达式、对比表达式、指代、是否询问单个实体（`expects_single_entity`）、识别出的歧义点；
2. 意图中包含指代（"这个 / 该 + 维度"）时，程序按 §6.5 解析；无法唯一解析 → `AMBIGUOUS`；
3. 意图是比较类问题（增长、下降、变化最多）且没有对比期时，程序按 §6.6 声明默认对比期，**不作为歧义**；
4. 存在未解决的口径歧义 → `AMBIGUOUS`；
5. 存在候选指标 → 调用编译器，按错误码处理；
6. 不存在候选指标、问题与数据相关且业务含义明确 → `NOT_COVERED`，进入 SQL 路径；
7. 问题所需的数据不存在（例如利润，数据中没有成本信息），或时间范围超出数据覆盖范围 → `OUT_OF_SCOPE`。

### 5.2 错误码与行为

| 错误码 | 情况 | 行为 | 题目类别 |
| --- | --- | --- | --- |
| `AMBIGUOUS` | 口径存在影响结果的歧义，或指代无法唯一解析 | 澄清，任务进入 `waiting_user` | `must_clarify` |
| `NOT_COVERED` | 不涉及已定义指标，业务含义明确 | 进入 SQL 路径，沿用已确认的口径 | `long_tail_sql` |
| `INCOMPATIBLE` | 涉及已定义指标，但维度或拆分方式不支持 | **不回退到 SQL**；说明限制，给出兼容的替代口径；记录为语义层待新增项 | `unsupported` |
| `INVALID_VALUE` | 筛选取值不存在 | 列出相近的合法取值，请用户确认 | — |
| `OUT_OF_SCOPE` | 数据中不存在所需信息，或时间超出覆盖范围 | 说明原因，不猜测 | `unsupported` |
| `PERMISSION_DENIED` | 权限不足 | 拒绝，不回退 | `unsupported` |
| `COST_REJECTED` | 成本检查拒绝（P1） | 建议缩小范围，改写后仍受同样的限制 | — |
| `COMPILER_ERROR` | 编译器内部异常 | 记录故障并告知用户，不回退 | — |

### 5.3 SQL 路径的约束

- 只能访问 `dws` schema 中的表，不能访问 `ods`（数据库权限层面不授予）；
- 使用与指标路径相同的数据库角色、护栏与 `REFERENCE_DATE`；
- 提示词中提供：DWS 表的结构与字段说明、当前 `confirmed_context`、解析后的绝对时间范围与指代结果；
- 时间条件必须使用程序解析出的绝对日期，`CURRENT_DATE`、`NOW()` 等函数被护栏拒绝；
- 执行报错后最多修复 `MAX_SQL_REPAIR` 次；
- 答案必须列出所采用的口径假设，并以 `default_declared` 状态写入 `confirmed_context`。

## 6. 对话状态（`agent/context.py`）

### 6.1 结构

使用 README §7.1 定义的 `ConfirmedContext`，包含 `last_result`。`rules` 中的每条口径带有来源：

```python
class Rule(TypedDict):
    text: str                                      # 如 "销售额按商品金额统计"
    source: Literal["user_confirmed", "default_declared"]
```

### 6.2 更新操作

按 README §7.1 的操作表实现：`set_filter`、`add_filter_values`、`remove_filter`、`set_time_range`、`set_compare_to`、`clear_compare`、`bind_reference`、`set_metrics`、`set_group_by`。每个操作在应用前由程序校验：维度存在、取值合法、与当前指标兼容；校验失败的操作不应用，并返回给模型说明原因。

### 6.3 时间表达式

模型输出结构化的时间表达式，由程序解析为绝对日期：

| 类型 | 示例 | 解析（设 `REFERENCE_DATE = 2018-09-01`） |
| --- | --- | --- |
| `month(offset)` | 上个月：`month(-1)` | 2018-08-01 至 2018-09-01 |
| `quarter(offset)` | 上季度：`quarter(-1)` | 2018-04-01 至 2018-07-01 |
| `last_n_months(n)` | 最近 3 个月 | 2018-06-01 至 2018-09-01 |
| `absolute_month(y, m)` | 2018 年 3 月 | 2018-03-01 至 2018-04-01 |
| `absolute_quarter(y, q)` | 2018 年第一季度 | 2018-01-01 至 2018-04-01 |
| `previous_period` | 再上一期（相对当前 `time_range`，长度相同） | 当前为 2018 Q2 时，解析为 2018-01-01 至 2018-04-01 |
| `year_over_year` | 去年同期（当前 `time_range` 平移 12 个月） | 当前为 2018 Q2 时，解析为 2017-04-01 至 2017-07-01 |

`month(0)`、`quarter(0)` 等指向数据不完整的时间段时，返回 `OUT_OF_SCOPE`。

### 6.4 持久化

- 表 `app.session_context(session_id, version, context_json, source_task_id, created_at)`，只追加，不覆盖；
- 用户通过 `/tasks/{id}/reply` 回复后，Agent 的第一个节点 `apply_reply` 将回复解析为更新操作，校验后**在执行任何查询之前**写入新版本；
- Agent 声明默认口径或默认对比期时，以 `default_declared` 写入；用户之后明确确认或修改时，更新为 `user_confirmed` 或替换；
- 每次给出答案后，写入本轮的 `last_result`，产生一个新版本；
- 每次写入新版本时，计算与上一版本的差异，通过 SSE 的 `context_update` 事件推送（§8.2）；
- 答案的口径说明中记录所依据的 `version`。

### 6.5 指代解析（`bind_reference`）

**写入 `last_result` 的规则（`answer` 节点）：**

- `dimension`：本轮结果的分组维度；`group_by` 恰好有一个维度时取该维度，否则为空；
- `entities`：按结果顺序排列的该维度取值；
- `selected`：意图中 `expects_single_entity` 为真（"最高的""下降最多的""哪个"）且结果第一名唯一时，取第一行的维度取值；第一名并列，或问题询问的是多个实体（"前 5 个"）时为空。

**解析规则：**

| 情况 | 行为 |
| --- | --- |
| `last_result.selected` 存在，且 `dimension` 与指代的维度一致 | 转换为 `set_filter(dim, in [selected])`；口径说明写明"'这个类目'指 X" |
| `selected` 为空，`entities` 有多个 | `AMBIGUOUS`：列出候选（最多 5 个）请用户选择 |
| `dimension` 与指代的维度不一致 | `AMBIGUOUS` |
| 没有 `last_result` | `AMBIGUOUS` |

### 6.6 比较类问题的基准

- 意图为比较类问题（增长、下降、变化最多），且 `compare_to` 为空时，按 `previous_period` 设置 `compare_to`，并写入一条 `default_declared` 口径："变化默认与相同长度的上一期比较"；
- 声明的默认对比期必须出现在答案的口径说明和界面的条件面板中；
- 用户随后说"和去年同期比"时，执行 `set_compare_to(year_over_year)`，口径来源改为 `user_confirmed`；
- 意图不是比较类问题时，不设置 `compare_to`。

## 7. 护栏（`mcp_server/guard.py`）

| 规则 | 实现 |
| --- | --- |
| 只读 | 查询角色只有 `dws` schema 的 `SELECT` 权限 |
| 单条 SELECT | sqlglot（Postgres 方言）解析，只接受一条 `SELECT`（含 `WITH ... SELECT`） |
| 函数白名单 | 只允许下列函数，其余一律拒绝 |
| 系统表 | 拒绝引用 `pg_catalog`、`information_schema`（schema 信息由工具提供） |
| 当前时间函数 | 拒绝 `CURRENT_DATE`、`CURRENT_TIMESTAMP`、`NOW()` 等，提示使用解析后的绝对日期 |
| LIMIT | 无 LIMIT 时追加 `ROW_LIMIT`；已有 LIMIT 时取较小值 |
| 超时 | 每个事务内 `SET LOCAL statement_timeout = STATEMENT_TIMEOUT_MS` |

**MVP 函数白名单：**

- 聚合：`COUNT`、`SUM`、`AVG`、`MIN`、`MAX`（允许 `FILTER`、`DISTINCT`）
- 条件与空值：`CASE`、`COALESCE`、`NULLIF`
- 类型：`CAST` / `::`
- 日期：`DATE_TRUNC`、`EXTRACT`、`DATE_PART`、日期与区间的加减
- 字符串：`LOWER`、`UPPER`、`TRIM`、`LENGTH`、`SUBSTRING`、`CONCAT`
- 数值：`ROUND`、`ABS`、`FLOOR`、`CEIL`
- 窗口：`ROW_NUMBER`、`RANK`、`DENSE_RANK`、`LAG`、`LEAD`（配合 `OVER`）

**`run_sql` 的错误码：** `NOT_SELECT`、`MULTI_STATEMENT`、`FUNCTION_NOT_ALLOWED`、`SYSTEM_CATALOG`、`SQL_SYNTAX`、`UNKNOWN_TABLE`、`UNKNOWN_COLUMN`、`TIMEOUT`、`PERMISSION_DENIED`。错误信息要足够具体，让模型可以据此修复。

## 8. API、事件与演示界面（P0）

### 8.1 接口

| 方法 | 路径 | 请求 | 响应 |
| --- | --- | --- | --- |
| POST | `/tasks` | `{question, db_id, session_id?}` | `{task_id, session_id}` |
| GET | `/tasks/{id}` | — | 任务状态与最终答案 |
| GET | `/tasks/{id}/events` | — | SSE 事件流 |
| POST | `/tasks/{id}/reply` | `{text}` 或 `{choice}` | `{status}` |
| GET | `/sessions/{id}` | — | 会话历史与最新的 `confirmed_context` |
| GET | `/health` | — | 健康检查 |

### 8.2 SSE 事件类型

| 事件 | 内容 |
| --- | --- |
| `status` | 任务状态变化 |
| `clarification` | 澄清问题与可选项（如指代的候选实体） |
| `tool_call` | 工具名与参数摘要 |
| `tool_result` | 结果摘要或错误码 |
| `context_update` | 新版本号，以及与上一版本的差异：`added`、`changed`、`removed`，每项带来源（`user_confirmed` / `default_declared`） |
| `answer` | 最终答案 |
| `error` | 任务级错误 |

`context_update` 示例：

```json
{
  "version": 4,
  "diff": {
    "added":   [{"field": "filters.customer_state", "value": {"op": "in", "values": ["SP"]}, "source": "user_confirmed"}],
    "changed": [],
    "removed": []
  }
}
```

### 8.3 答案结构

```json
{
  "summary": "上季度销售额下降最多的类目是 ...",
  "table": {"columns": ["category", "value_current", "value_compare", "delta", "delta_pct"], "rows": [["...", 0, 0, 0, 0]]},
  "explanation": {
    "path": "metric",
    "metric": {"id": "category_sales", "definition": "销售额按商品金额统计，不含运费，不含已取消和不可用的订单，按下单时间归属"},
    "attribution": null,
    "reference": null,
    "source_tables": ["dws.order_item"],
    "filters": {},
    "time_range": {"expr": "上季度", "start": "2018-04-01", "end": "2018-07-01"},
    "compare_to": {"expr": "再上一期（默认）", "start": "2018-01-01", "end": "2018-04-01", "source": "default_declared"},
    "assumptions": ["变化默认与相同长度的上一期比较"],
    "sql": "WITH t AS (...) SELECT ...",
    "reference_date": "2018-09-01",
    "context_version": 3
  }
}
```

指代被解析时，`reference` 为 `{"expr": "这个类目", "dimension": "category", "value": "...", "from_version": 3}`。

### 8.4 演示界面（`ui/app.py`）

用 Streamlit 实现，**只通过 HTTP / SSE 调用 API**，不导入 Agent 代码。

| 区域 | 内容 |
| --- | --- |
| 对话区 | 多轮对话；`clarification` 事件的可选项显示为按钮，点击后调用 `/reply` |
| 条件面板 | 显示当前 `confirmed_context`：指标、口径、筛选、时间范围、对比期、上一轮结果的选中实体；收到 `context_update` 时，新增的条目标绿、修改的标黄、删除的以删除线显示一轮；每条标注来源（"你确认的" / "系统默认"） |
| 结果区 | 结果表格；可展开查看 SQL 与完整口径说明；指代被解析时显示"'这个类目'指 X" |
| 执行过程 | 按时间顺序显示 `status`、`tool_call`、`tool_result` 事件 |

界面不实现任何业务逻辑：条件的变化完全来自 `context_update` 事件，界面只负责展示。这样界面显示的就是后端真实的状态。

## 9. 首批测试用例

### 9.1 Fixture 数据库（`semantic/tests/fixtures.sql`）

手工构造的小型数据，用于验证粒度、去重、空值与归属规则：

| 订单 | 状态 | 客户州 | 明细（类目：金额） | 评价（评分） |
| --- | --- | --- | --- | --- |
| O1 | delivered | SP | electronics：100；toys：50 | R1（2） |
| O2 | canceled | RJ | electronics：80 | R2（5） |
| O3 | delivered | SP | toys：30 | R3（空） |
| O4 | delivered | RJ | electronics：70 | — |

O1 另有一条付款记录 160（含运费），用于确认付款金额**不会**进入销售额。

### 9.2 语义层与编译器（`semantic/tests/`）

| 编号 | 用例 | 期望结果 |
| --- | --- | --- |
| U1 | `dws.order_item` 行数 | 5 行（与明细数一致），唯一键无重复 |
| U2 | 类目销售额，按类目 | electronics = 170（O2 已取消，不计入），toys = 80 |
| U3 | 类目销售额，总计 | 250，且等于各类目之和（可加性检查） |
| U4 | 类目销售额，客户州 = SP | electronics = 100，toys = 80 |
| U5 | 类目销售额按 `seller_state` 分组 | 返回 `INCOMPATIBLE` |
| U6 | 差评率，总体 | 分子 1、分母 2、值 0.5（R3 评分为空，不计入分母；不是 1/3） |
| U7 | 差评率，按类目 | electronics：分子 1、分母 2、值 0.5；toys：分子 1、分母 1、值 1.0；结果带 `additive_across: false` |
| U8 | 差评率，分母为 0 的范围 | 值为空，附带"没有有效评分"说明 |
| U9 | 时间边界 | `end` 当天的数据不计入（左闭右开） |
| U10 | `compare_to` | 同时返回两个时间段的值，差值与变化率计算正确；按 `delta` 升序排序 |
| U11 | 非法筛选取值（不存在的州） | 返回 `INVALID_VALUE` |
| U12 | 编译器内部异常（注入） | 返回 `COMPILER_ERROR`，不被当作 `NOT_COVERED` |

### 9.3 对话状态（`tests/context/`）

| 编号 | 用例 | 期望结果 |
| --- | --- | --- |
| C1 | 已有 SP 筛选，`set_filter(customer_state, [RJ])` | 筛选变为 RJ（替换） |
| C2 | 已有 SP 筛选，`add_filter_values(customer_state, [RJ])` | 筛选变为 SP、RJ |
| C3 | `remove_filter(customer_state)` | 不再按州筛选 |
| C4 | `set_time_range(quarter(-1))` | 解析为 2018-04-01 至 2018-07-01 |
| C5 | 当前为 Q2，`set_compare_to(previous_period)` | 解析为 2018-01-01 至 2018-04-01 |
| C6 | `set_filter` 使用不存在的维度 | 拒绝，状态不变 |
| C7 | 每次成功更新 | `version` 加 1，旧版本保留 |
| C8 | 回复澄清后、执行查询前模拟进程退出 | 重启后数据库中已有新版本的 `confirmed_context` |
| C9 | `last_result` 维度为 category、`selected` 为 X，`bind_reference(category)` | 筛选变为 category in [X] |
| C10 | `last_result` 有 5 个实体、`selected` 为空，`bind_reference(category)` | `AMBIGUOUS`，候选为这 5 个实体 |
| C11 | `last_result` 维度为 customer_state，`bind_reference(category)` | `AMBIGUOUS` |
| C12 | 没有 `last_result`，`bind_reference(category)` | `AMBIGUOUS` |
| C13 | 比较类意图、当前为 Q2、`compare_to` 为空 | `compare_to` 为 2018-01-01 至 2018-04-01，新增一条 `default_declared` 口径 |
| C14 | 当前为 Q2，`set_compare_to(year_over_year)` | 解析为 2017-04-01 至 2017-07-01，口径来源变为 `user_confirmed` |
| C15 | `expects_single_entity` 为真，结果第一名并列 | `selected` 为空 |
| C16 | 两个版本之间新增筛选、修改时间范围、删除对比期 | `context_update` 的 `added`、`changed`、`removed` 各一项 |

### 9.4 护栏（`tests/guard/`）

| 编号 | 输入 | 期望结果 |
| --- | --- | --- |
| G1 | `DELETE FROM dws.order_item` | `NOT_SELECT` |
| G2 | `SELECT 1; SELECT 2` | `MULTI_STATEMENT` |
| G3 | `SELECT set_config('app.allowed_states', 'RJ', true)` | `FUNCTION_NOT_ALLOWED` |
| G4 | `SELECT pg_sleep(10)` | `FUNCTION_NOT_ALLOWED` |
| G5 | `SELECT * FROM information_schema.tables` | `SYSTEM_CATALOG` |
| G6 | `... WHERE purchase_ts >= CURRENT_DATE - INTERVAL '1 month'` | `FUNCTION_NOT_ALLOWED`，提示使用绝对日期 |
| G7 | `SELECT * FROM ods.orders` | `PERMISSION_DENIED`（数据库权限层面拒绝） |
| G8 | 无 LIMIT 的查询 | 自动追加 `LIMIT ROW_LIMIT` |
| G9 | 在数据库层直接执行慢查询 | 超过 `STATEMENT_TIMEOUT_MS` 后返回 `TIMEOUT` |

### 9.5 路由（`tests/router/`）

| 编号 | 问题 | 期望错误码 / 路径 |
| --- | --- | --- |
| R1 | 上季度销售额最高的 5 个类目 | 指标路径 |
| R2 | 上个月平均每笔订单包含几件商品 | `NOT_COVERED` → SQL 路径 |
| R3 | 上季度销量最好的类目（"销量"指件数还是金额） | `AMBIGUOUS` |
| R4 | 按付款金额统计各类目销售额 | `INCOMPATIBLE`，不进入 SQL 路径 |
| R5 | 上季度各类目的利润 | `OUT_OF_SCOPE` |
| R6 | 本月销售额 | `OUT_OF_SCOPE`（数据不完整） |
| R7 | 上季度哪个类目的销售额下降最多 | 指标路径，声明默认对比期，按 `delta` 升序 |

路由测试依赖模型，作为评测用例运行（§10），不作为确定性单元测试。

### 9.6 RLS 与安全测试清单（P1 实现，此处先固定）

| 编号 | 用例 |
| --- | --- |
| S1 | 查询角色的 `rolsuper`、`rolbypassrls` 均为 false，且不是任何 DWS 表的所有者 |
| S2 | DWS 表均启用 `FORCE ROW LEVEL SECURITY` |
| S3 | 设置可见范围为 SP 后，查询只返回 SP 的数据；指标路径与 SQL 路径结果一致 |
| S4 | 同一连接上交替处理 SP 用户与 RJ 用户的请求，不会遗留上一用户的可见范围 |
| S5 | 生成的 SQL 尝试修改会话参数，被护栏拒绝（同 G3） |
| S6 | 用户 A 使用用户 B 的 `result_ref`，被拒绝 |
| S7 | 缓存命中时不会返回其他可见范围的结果 |

## 10. 评测题（P0）

### 10.1 开发集示例（扩展到约 20 题）

| 类别 | 问题 | 期望行为 |
| --- | --- | --- |
| `metric_covered` | 上个季度销售额最高的 5 个类目是什么？ | 指标路径，按类目分组，取前 5 |
| `metric_covered` | 上个月圣保罗州的销售额是多少？ | 指标路径，筛选 SP |
| `metric_covered` | 上季度哪个州的差评率最高？ | 指标路径，按客户州分组 |
| `metric_covered` | 上季度和再上一季度相比，哪个类目的销售额增长最多？ | 指标路径，带 `compare_to`，按 `delta` 降序 |
| `metric_covered` | 上季度哪个类目的销售额下降最多？ | 指标路径，声明默认对比期，按 `delta` 升序 |
| `metric_covered` | 2018 年第一季度 electronics 类目的差评率是多少？ | 指标路径，经桥接表，说明归属规则 |
| `long_tail_sql` | 上个月平均每笔订单包含几件商品？ | SQL 路径 |
| `long_tail_sql` | 上季度已签收订单的平均配送天数是多少？ | SQL 路径，使用 `delivered_ts - purchase_ts` |
| `long_tail_sql` | 上个月卖家数量最多的是哪个州？ | SQL 路径 |
| `must_clarify` | 上季度销量最好的类目？ | 澄清"销量"指件数还是金额 |
| `must_clarify` | 最近哪个类目表现最差？ | 澄清指标与时间范围 |
| `unsupported` | 上季度各类目的利润是多少？ | `OUT_OF_SCOPE`：数据中没有成本信息 |
| `unsupported` | 按付款金额统计各类目的销售额 | `INCOMPATIBLE`：说明付款是订单级，提供按商品金额的替代口径 |
| `unsupported` | 哪个卖家州的销售额最高？ | `INCOMPATIBLE`：MVP 未定义卖家州维度 |
| `unsupported` | 本月的销售额是多少？ | `OUT_OF_SCOPE`：本月数据不完整 |

### 10.2 多轮对话（约 6 组）

**D1 销售额：默认对比期、筛选、改为同比**

```
用户：上季度哪个类目的销售额下降最多？
Agent：[声明销售额按商品金额统计、默认与再上一季度比较；说明按付款金额拆分到类目不支持；请求确认]
用户：可以。
Agent：[结果；context_update 新增 compare_to（系统默认）]
用户：只看圣保罗州。
期望：set_filter(customer_state, [SP])
用户：改成和去年同期比。
期望：set_compare_to(year_over_year)，口径来源变为 user_confirmed；州筛选保留
```

**D2 差评率：归属规则与排除**

```
用户：上季度的差评率是多少？
Agent：[结果，说明空评分不计入分母]
用户：按类目看。
期望：set_group_by([category])；答案说明归属规则，且提示各类目数值不能相加
用户：去掉 unknown 类目。
期望：set_filter(category, not_in [unknown])
```

**D3 条件的新增、替换与删除**

```
用户：上个月的销售额是多少？
用户：只看圣保罗州。       期望：set_filter(customer_state, [SP])
用户：再加上里约。          期望：add_filter_values(customer_state, [RJ])
用户：改成上季度。          期望：set_time_range(quarter(-1))，州筛选保留
用户：不限州了。            期望：remove_filter(customer_state)
```

**D4 指代：单个实体，指标路径到 SQL 路径**

```
用户：上季度销售额最高的类目是哪个？
期望：last_result.selected 为第一名的类目
用户：这个类目上季度平均每单买几件？
期望：bind_reference(category) 解析为该类目；NOT_COVERED，进入 SQL 路径，沿用类目与时间范围；口径说明写明指代结果
```

**D5 不支持的追问**

```
用户：上季度各州的销售额。
用户：按卖家所在州再拆一下。
期望：INCOMPATIBLE，不进入 SQL 路径；说明限制，保持原有结果与状态不变
```

**D6 指代：多个候选时追问**

```
用户：上季度销售额前 5 的类目。
期望：last_result 有 5 个实体，selected 为空
用户：这个类目的差评率呢？
期望：AMBIGUOUS，clarification 事件列出 5 个候选
用户：[选择第 2 个]
期望：bind_reference 解析为第 2 个类目，查询其差评率，口径说明写明归属规则
```

### 10.3 冻结测试集

- P0 结束前编写约 30 道单轮题（四个类别都要覆盖）和 6 组多轮对话；
- 编写完成后记录文件哈希到 `docs/experiments.md`，之后不修改；
- 只在里程碑运行，不查看单题失败细节来调整提示词或规则。

## 11. 实现顺序

1. 数据导入与画像（§1），确定 `REFERENCE_DATE`；
2. DWS 宽表与断言（§2）；
3. 语义层定义、编译器与 fixture 单元测试（§3、§4、§9.1–9.2）；
4. 护栏与测试（§7、§9.4）；
5. MCP 工具：`list_metrics`、`query_metric`、`describe_table`、`run_sql`；
6. 对话状态与测试，含指代与比较基准（§6、§9.3）；
7. LangGraph Agent：节点、路由、修错循环、可解释答案（§5）；
8. FastAPI 接口与 SSE，含 `context_update`（§8.1–8.3）；
9. Streamlit 演示界面（§8.4）；
10. Langfuse 追踪；
11. 评测 harness 与开发集、多轮对话（§10）；
12. 模型网关接入 API 模型与小模型推理端点，跑对照链步骤 1–2。

## 12. 完成标准

MVP 完成时达到 README §12 验收标准的第 1 条，并满足以下各项：

- [ ] `docker compose up` 一条命令启动数据库、API 与演示界面；
- [ ] 数据画像报告生成，所有假设的验证结果已记录，`REFERENCE_DATE` 已确定；
- [ ] §9.2–9.4 的单元测试全部通过；
- [ ] D1–D6 六组多轮对话在演示界面上端到端运行，条件面板的变化与 `confirmed_context` 一致；
- [ ] 开发集在 API 模型与小模型上各跑一遍，按题目类别输出结果；
- [ ] 冻结测试集已编写并记录哈希；
- [ ] Langfuse 中可以看到完整轨迹；
- [ ] README §13 中 P0 的三个演示案例可以通过脚本或界面复现，并录制演示视频；
- [ ] 对照链步骤 1–2 的结果记录在 `docs/experiments.md`。
