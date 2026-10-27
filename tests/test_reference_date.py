from datetime import date

import pytest

from data.reference_date import add_months, determine_reference_date


def months(start: date, counts: list[int]) -> dict[date, int]:
    """从 start 开始，按顺序给每个月分配订单数。"""
    return {add_months(start, i): n for i, n in enumerate(counts)}


def test_real_olist_tail():
    # 真实 Olist 数据 2018 年各月的订单数（阶段 5.3 查到的）
    data = months(date(2018, 1, 1), [7269, 6728, 7211, 6939, 6873, 6167, 6292, 6512, 16, 4])
    r = determine_reference_date(data)
    assert r.last_complete_month == date(2018, 8, 1)
    assert r.reference_date == date(2018, 9, 1)
    assert r.trace[0].prior_median == 6402        # 2018-10 之前 6 个月的中位数
    assert r.trace[-1].prior_median == 6800.5     # 2018-08 之前 6 个月的中位数


def test_last_month_complete():
    data = months(date(2018, 1, 1), [100] * 8)
    r = determine_reference_date(data)
    assert r.reference_date == date(2018, 9, 1)
    assert len(r.trace) == 1


def test_threshold_boundary_is_inclusive():
    # 之前 6 个月中位数 100，阈值 50：恰好 50 算完整，49 不算
    data = months(date(2018, 1, 1), [100] * 6 + [50])
    assert determine_reference_date(data).last_complete_month == date(2018, 7, 1)
    data = months(date(2018, 1, 1), [100] * 6 + [49])
    assert determine_reference_date(data).last_complete_month == date(2018, 6, 1)


def test_missing_months_count_as_zero():
    # 2018-08 一笔订单都没有（字典里没有这个键），必须按 0 处理，而不是被跳过
    data = {date(2018, m, 1): 100 for m in range(1, 8)}
    data[date(2018, 9, 1)] = 3
    r = determine_reference_date(data)
    assert r.last_complete_month == date(2018, 7, 1)
    assert [t.month for t in r.trace] == [date(2018, 9, 1), date(2018, 8, 1), date(2018, 7, 1)]


def test_year_boundary():
    data = months(date(2017, 7, 1), [100, 100, 100, 100, 100, 100, 100, 1])
    r = determine_reference_date(data)
    assert r.last_complete_month == date(2018, 1, 1)
    assert r.reference_date == date(2018, 2, 1)


@pytest.mark.parametrize(
    "d, n, expected",
    [
        (date(2018, 1, 1), 1, date(2018, 2, 1)),
        (date(2018, 12, 1), 1, date(2019, 1, 1)),
        (date(2018, 1, 1), -1, date(2017, 12, 1)),
        (date(2018, 3, 15), 0, date(2018, 3, 1)),
    ],
)
def test_add_months(d, n, expected):
    assert add_months(d, n) == expected


def test_empty_input_raises():
    with pytest.raises(ValueError):
        determine_reference_date({})