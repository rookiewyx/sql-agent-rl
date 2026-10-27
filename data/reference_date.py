"""根据月度订单数确定 REFERENCE_DATE（规则见 docs/mvp_spec.md §1.3）。

规则：
1. 计算每个自然月的订单数（首末月之间缺失的月份记为 0）；
2. 从最后一个月往前找，第一个订单数不低于"其之前 6 个月订单数中位数"一半的月份，
   记为最后一个完整月；
3. REFERENCE_DATE = 最后一个完整月的次月 1 日。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from statistics import median


def add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    return date(d.year + y, m + 1, 1)


@dataclass
class MonthCheck:
    month: date
    orders: int
    prior_median: float | None
    threshold: float | None
    complete: bool


@dataclass
class ReferenceDateResult:
    last_complete_month: date
    reference_date: date
    trace: list[MonthCheck] = field(default_factory=list)   # 从最后一个月往前，直到选中的月份
    window: int = 6
    ratio: float = 0.5


def fill_months(monthly: dict[date, int]) -> list[tuple[date, int]]:
    if not monthly:
        raise ValueError("没有任何月度订单数据")
    months = sorted(monthly)
    out, cur = [], months[0]
    while cur <= months[-1]:
        out.append((cur, monthly.get(cur, 0)))
        cur = add_months(cur, 1)
    return out


def determine_reference_date(
    monthly: dict[date, int], window: int = 6, ratio: float = 0.5
) -> ReferenceDateResult:
    series = fill_months({date(m.year, m.month, 1): n for m, n in monthly.items()})
    trace: list[MonthCheck] = []
    for i in range(len(series) - 1, -1, -1):
        month, orders = series[i]
        prior = [n for _, n in series[max(0, i - window):i]]
        if not prior:
            # 第一个月之前没有可比较的月份，只能把它当作完整月
            trace.append(MonthCheck(month, orders, None, None, True))
            break
        med = float(median(prior))
        threshold = med * ratio
        complete = orders > 0 and orders >= threshold
        trace.append(MonthCheck(month, orders, med, threshold, complete))
        if complete:
            break
    chosen = trace[-1].month
    return ReferenceDateResult(chosen, add_months(chosen, 1), trace, window, ratio)