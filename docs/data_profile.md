# Olist 数据画像

> 由 `python -m data.profile_olist` 自动生成于 2026-10-27T07:59:52+00:00。请勿手工修改；数据变化后重新运行。

## 数据版本

| 表 | 文件 | 行数 | SHA-256 |
| --- | --- | --- | --- |
| `ods.category_translation` | `product_category_name_translation.csv` | 71 | `a81f0d1f27b27e72…` |
| `ods.customers` | `olist_customers_dataset.csv` | 99,441 | `983a422239e1712d…` |
| `ods.order_items` | `olist_order_items_dataset.csv` | 112,650 | `0bc4d068c4fe38cb…` |
| `ods.order_payments` | `olist_order_payments_dataset.csv` | 103,886 | `4f713964f2815dbb…` |
| `ods.order_reviews` | `olist_order_reviews_dataset.csv` | 99,224 | `012b61c7593e34f5…` |
| `ods.orders` | `olist_orders_dataset.csv` | 99,441 | `8df58ef3d2d7e994…` |
| `ods.products` | `olist_products_dataset.csv` | 32,951 | `3e6569628a17fbc7…` |
| `ods.sellers` | `olist_sellers_dataset.csv` | 3,095 | `1f643d2b950373b8…` |

数据目录：`data/raw`

## 检查结果汇总

| 编号 | 检查项 | 状态 | 结论 |
| --- | --- | --- | --- |
| P1 | orders.order_id 唯一 | ✅ PASS | 99,441 行，(order_id) 唯一，无空键。 |
| P2 | order_items (order_id, order_item_id) 唯一 | ✅ PASS | 112,650 行，(order_id, order_item_id) 唯一，无空键。 |
| P3 | customers.customer_id 唯一 | ✅ PASS | 99,441 行，(customer_id) 唯一，无空键。 |
| P4 | products.product_id 唯一；类目空值 | ✅ PASS | 32,951 行，(product_id) 唯一，无空键。 类目为空的商品 610 个（空字符串 0 个），涉及明细 1,603 条（占全部明细 1.42%）。 |
| P5 | 类目翻译覆盖率 | ℹ️ INFO | 翻译表 71 行，键唯一；商品类目 73 个，其中 2 个没有英文翻译。 |
| P6 | 评价表的唯一键与评分 | ✅ PASS | 99,224 行；review_id 去重后 98,410 个，其中 789 个 review_id 对应多笔订单；(review_id, order_id) 去重后 99,224 个；评分为空 0 行。 |
| P7 | 订单状态取值 | ✅ PASS | 共 8 种状态：delivered（96,478）、shipped（1,107）、canceled（625）、unavailable（609）、invoiced（314）、processing（301）、created（5）、approved（2）。 |
| P8 | 下单时间范围与 REFERENCE_DATE | ℹ️ INFO | 下单时间范围 2016-09-04 21:15:19 至 2018-10-17 17:30:18，下单时间为空 0 行。最后一个完整月为 2018-08，REFERENCE_DATE = 2018-09-01。 |
| P9 | 参照完整性 | ✅ PASS | 所有关联键都能找到对应记录。 |
| P10 | 没有明细的订单 | ℹ️ INFO | 没有任何明细的订单 775 笔；这些订单上的评价 759 条（占全部评价 0.76%）。 |

## REFERENCE_DATE：`2018-09-01`

最后一个完整月为 **2018-08**。规则见 `docs/mvp_spec.md` §1.3（之前 6 个月中位数 × 0.5）。

## 对宽表设计的影响

- **P4**：类目为空的商品在宽表中记为 unknown。
- **P5**：没有翻译的类目在宽表中保留原始葡萄牙语名称。
- **P6**：review_id 单独不能作为主键，dws.review 使用 (review_id, order_id)。 当前数据中没有空评分，差评率的空值规则仍保留，用于防御后续数据。
- **P7**：指标定义中的排除条件 order_status NOT IN ('canceled', 'unavailable') 与实际取值一致。
- **P8**："上个月"解析为 2018-08；2018-09 及之后的月份按数据不完整处理（OUT_OF_SCOPE）。
- **P9**：dws.order_item 预期 112,650 行（ods.order_items 共 112,650 行）；dws.review 预期 99,224 行。第 2 步的行数断言使用这两个数字。
- **P10**：差评率按类目拆分时，这 759 条评价不计入任何类目；按客户州或总体统计时仍然计入。答案的口径说明需要提示这一覆盖范围差异。

没有 FAIL 项，可以按 `docs/mvp_spec.md` §2 进行第 2 步。

## 检查明细

### P1 orders.order_id 唯一　✅ PASS

99,441 行，(order_id) 唯一，无空键。

**影响：** 无。

### P2 order_items (order_id, order_item_id) 唯一　✅ PASS

112,650 行，(order_id, order_item_id) 唯一，无空键。

**影响：** 无。

### P3 customers.customer_id 唯一　✅ PASS

99,441 行，(customer_id) 唯一，无空键。

**影响：** 无。

### P4 products.product_id 唯一；类目空值　✅ PASS

32,951 行，(product_id) 唯一，无空键。 类目为空的商品 610 个（空字符串 0 个），涉及明细 1,603 条（占全部明细 1.42%）。

**影响：** 类目为空的商品在宽表中记为 unknown。

### P5 类目翻译覆盖率　ℹ️ INFO

翻译表 71 行，键唯一；商品类目 73 个，其中 2 个没有英文翻译。

**影响：** 没有翻译的类目在宽表中保留原始葡萄牙语名称。

**没有英文翻译的类目**

| 类目（原始名称） | 商品数 | 明细数 |
| --- | --- | --- |
| portateis_cozinha_e_preparadores_de_alimentos | 10 | 15 |
| pc_gamer | 3 | 9 |

### P6 评价表的唯一键与评分　✅ PASS

99,224 行；review_id 去重后 98,410 个，其中 789 个 review_id 对应多笔订单；(review_id, order_id) 去重后 99,224 个；评分为空 0 行。

**影响：** review_id 单独不能作为主键，dws.review 使用 (review_id, order_id)。 当前数据中没有空评分，差评率的空值规则仍保留，用于防御后续数据。

**每笔订单的评价数**

| 评价数 | 订单数 |
| --- | --- |
| 1 | 98,126 |
| 2 | 543 |
| 3+ | 4 |

**评分分布**

| 评分 | 评价数 |
| --- | --- |
| 1 | 11,424 |
| 2 | 3,151 |
| 3 | 8,179 |
| 4 | 19,142 |
| 5 | 57,328 |

### P7 订单状态取值　✅ PASS

共 8 种状态：delivered（96,478）、shipped（1,107）、canceled（625）、unavailable（609）、invoiced（314）、processing（301）、created（5）、approved（2）。

**影响：** 指标定义中的排除条件 order_status NOT IN ('canceled', 'unavailable') 与实际取值一致。

**订单状态**

| 状态 | 订单数 |
| --- | --- |
| delivered | 96,478 |
| shipped | 1,107 |
| canceled | 625 |
| unavailable | 609 |
| invoiced | 314 |
| processing | 301 |
| created | 5 |
| approved | 2 |

### P8 下单时间范围与 REFERENCE_DATE　ℹ️ INFO

下单时间范围 2016-09-04 21:15:19 至 2018-10-17 17:30:18，下单时间为空 0 行。最后一个完整月为 2018-08，REFERENCE_DATE = 2018-09-01。

**影响：** "上个月"解析为 2018-08；2018-09 及之后的月份按数据不完整处理（OUT_OF_SCOPE）。

**尾部月份的判定过程（从最后一个月往前）**

| 月份 | 订单数 | 之前 6 个月中位数 | 阈值（中位数 × 0.5） | 是否完整 |
| --- | --- | --- | --- | --- |
| 2018-10 | 4 | 6402 | 3201 | 否 |
| 2018-09 | 16 | 6692.5 | 3346.25 | 否 |
| 2018-08 | 6,512 | 6800.5 | 3400.25 | 是 |

**月度订单数**

| 月份 | 订单数 |
| --- | --- |
| 2016-09 | 4 |
| 2016-10 | 324 |
| 2016-12 | 1 |
| 2017-01 | 800 |
| 2017-02 | 1,780 |
| 2017-03 | 2,682 |
| 2017-04 | 2,404 |
| 2017-05 | 3,700 |
| 2017-06 | 3,245 |
| 2017-07 | 4,026 |
| 2017-08 | 4,331 |
| 2017-09 | 4,285 |
| 2017-10 | 4,631 |
| 2017-11 | 7,544 |
| 2017-12 | 5,673 |
| 2018-01 | 7,269 |
| 2018-02 | 6,728 |
| 2018-03 | 7,211 |
| 2018-04 | 6,939 |
| 2018-05 | 6,873 |
| 2018-06 | 6,167 |
| 2018-07 | 6,292 |
| 2018-08 | 6,512 |
| 2018-09 | 16 |
| 2018-10 | 4 |

### P9 参照完整性　✅ PASS

所有关联键都能找到对应记录。

**影响：** dws.order_item 预期 112,650 行（ods.order_items 共 112,650 行）；dws.review 预期 99,224 行。第 2 步的行数断言使用这两个数字。

**找不到对应记录的关联键**

| 检查 | 行数 |
| --- | --- |
| 明细的 order_id 不在订单表 | 0 |
| 订单的 customer_id 不在客户表 | 0 |
| 明细的 product_id 不在商品表 | 0 |
| 明细的 seller_id 不在卖家表 | 0 |
| 评价的 order_id 不在订单表 | 0 |

### P10 没有明细的订单　ℹ️ INFO

没有任何明细的订单 775 笔；这些订单上的评价 759 条（占全部评价 0.76%）。

**影响：** 差评率按类目拆分时，这 759 条评价不计入任何类目；按客户州或总体统计时仍然计入。答案的口径说明需要提示这一覆盖范围差异。

**没有明细的订单（按状态）**

| 状态 | 订单数 |
| --- | --- |
| unavailable | 603 |
| canceled | 164 |
| created | 5 |
| invoiced | 2 |
| shipped | 1 |
