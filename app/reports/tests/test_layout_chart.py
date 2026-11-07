"""The chart: one point per category, counts and aggregates, blank «—» last, folding beyond 30 categories."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from reports import layouts as layouts_mod
from reports.filters import Filters
from reports.layouts import Chart, LayoutSpec
from reports.table import EMPTY_GROUP, Table
from reports.types import Column

TODAY = date(2026, 11, 7)

NAME = Column(key="name", label="Нэр", value=lambda r: r.name, kind="text")
DEPT = Column(key="dept", label="Хэлтэс", value=lambda r: r.dept, kind="text")
PAY = Column(key="pay", label="Цалин", value=lambda r: r.pay, kind="number", numeric=True, money=True)


def _row(name: str | None, dept: object, pay: object = 0) -> Any:
    return SimpleNamespace(name=name, dept=dept, pay=pay)


def _spec(value: tuple[Column | None, str] = (None, "count"), by: Column | None = DEPT) -> LayoutSpec:
    return LayoutSpec(layout="chart", by=by, by2=None, value=value, chart="bar", month=date(2026, 11, 1))


def _build(rows: list[Any], spec: LayoutSpec | None = None) -> Chart:
    spec = spec or _spec()
    table = Table(columns=[NAME, DEPT, PAY], groups=[], count=len(rows), filters=Filters(), rows=rows, spec=spec)
    return layouts_mod.build_chart(table, spec)


def test_count_of_rows_by_department() -> None:
    rows = [_row("Бат", "Санхүү"), _row("Дорж", "Ачаа"), _row("Оюу", "Ачаа")]
    chart = _build(rows)
    assert [(p.label, p.value) for p in chart.points] == [("Ачаа", 2), ("Санхүү", 1)]
    assert chart.folded is False
    assert chart.kind == "bar"


def test_sum_of_pay_by_department_is_exact_and_money() -> None:
    rows = [
        _row("Бат", "Санхүү", pay=Decimal("1500000.50")),
        _row("Дорж", "Ачаа", pay=Decimal("900000")),
        _row("Оюу", "Ачаа", pay=Decimal("100000.25")),
    ]
    chart = _build(rows, _spec(value=(PAY, "sum")))
    assert [(p.label, p.value) for p in chart.points] == [
        ("Ачаа", Decimal("1000000.25")),
        ("Санхүү", Decimal("1500000.50")),
    ]
    assert all(p.money for p in chart.points)


def test_money_is_false_for_count_of_a_money_column() -> None:
    rows = [_row("Бат", "Санхүү", pay=5), _row("Дорж", "Санхүү", pay=None)]
    chart = _build(rows, _spec(value=(PAY, "count")))
    assert [(p.value, p.money) for p in chart.points] == [(2, False)]


def test_count_counts_rows_including_blank_values() -> None:
    rows = [_row("Бат", "Санхүү", pay=None), _row("Дорж", "Санхүү", pay=7)]
    chart = _build(rows, _spec(value=(PAY, "count")))
    assert chart.points[0].value == 2


def test_bucket_with_only_blank_values_gives_none() -> None:
    rows = [_row("Бат", "Санхүү", pay=None), _row("Дорж", "Ачаа", pay=3)]
    chart = _build(rows, _spec(value=(PAY, "sum")))
    values = {p.label: p.value for p in chart.points}
    assert values["Санхүү"] is None
    assert values["Ачаа"] == 3


def test_forty_categories_fold_into_busad_with_the_recomputed_total() -> None:
    rows = [_row(f"Нэр {i}", f"D{i:02d}", pay=i) for i in range(40)]
    chart = _build(rows, _spec(value=(PAY, "sum")))
    assert len(chart.points) == 30
    assert [p.label for p in chart.points[:29]] == [f"D{i:02d}" for i in range(29)]
    last = chart.points[-1]
    assert last.label == "Бусад"
    assert last.value == sum(range(29, 40))
    assert chart.folded is True


def test_folded_count_counts_the_folded_rows() -> None:
    rows = [_row(f"Нэр {i}", f"D{i:02d}") for i in range(35)]
    chart = _build(rows)
    assert chart.points[-1].label == "Бусад"
    assert chart.points[-1].value == 6  # D29 .. D34


def test_exactly_thirty_categories_do_not_fold() -> None:
    rows = [_row(f"Нэр {i}", f"D{i:02d}") for i in range(30)]
    chart = _build(rows)
    assert len(chart.points) == 30
    assert chart.folded is False
    assert all(p.label != "Бусад" for p in chart.points)


def test_blank_category_is_labelled_and_sorts_last() -> None:
    rows = [_row("Бат", None), _row("Дорж", "Ачаа"), _row("Оюу", "")]
    chart = _build(rows)
    assert [p.label for p in chart.points] == ["Ачаа", EMPTY_GROUP]
    assert chart.points[-1].value == 2
    assert chart.points[-1].label == "—"


def test_blank_category_beyond_the_cap_folds_like_any_other() -> None:
    rows = [_row("Бат", None)] + [_row(f"Нэр {i}", f"D{i:02d}") for i in range(30)]
    chart = _build(rows)
    assert len(chart.points) == 30
    assert chart.points[-1].label == "Бусад"
    assert chart.points[-1].value == 2  # D29 and the blank one
    assert chart.folded is True


def test_empty_rows_give_no_points() -> None:
    chart = _build([])
    assert chart.points == []
    assert chart.folded is False


def test_chart_kind_follows_the_spec() -> None:
    rows = [_row("Бат", "Санхүү")]
    spec = LayoutSpec(layout="chart", by=DEPT, by2=None, value=(None, "count"), chart="donut", month=date(2026, 11, 1))
    assert _build(rows, spec).kind == "donut"


def test_value_label_names_the_count_and_the_column() -> None:
    assert _build([_row("Бат", "X")]).value_label == "Тоо"
    assert "Цалин" in _build([_row("Бат", "X")], _spec(value=(PAY, "sum"))).value_label


def test_name_count_on_a_text_column_counts_rows_including_blank_names() -> None:
    rows = [_row(None, "Санхүү"), _row("Бат", "Санхүү"), _row("", "Ачаа")]
    chart = _build(rows, _spec(value=(NAME, "count")))
    assert [(p.label, p.value) for p in chart.points] == [("Ачаа", 1), ("Санхүү", 2)]
    assert all(p.money is False for p in chart.points)


def test_mixed_text_and_number_values_sum_only_the_numbers() -> None:
    rows = [_row("Бат", "X", pay="n/a"), _row("Дорж", "X", pay=5), _row("Оюу", "X", pay=Decimal("2.5"))]
    chart = _build(rows, _spec(value=(PAY, "sum")))
    assert chart.points[0].value == Decimal("7.5")


def test_min_over_mixed_text_and_number_values_is_none() -> None:
    rows = [_row("Бат", "X", pay="n/a"), _row("Дорж", "X", pay=5)]
    chart = _build(rows, _spec(value=(PAY, "min")))
    assert chart.points[0].value is None


def test_category_keys_of_any_type_are_labelled_without_error() -> None:
    rows = [_row("a", None), _row("b", 5), _row("c", Decimal("2.5")), _row("d", date(2026, 1, 2)), _row("e", True)]
    chart = _build(rows)
    assert [p.label for p in chart.points] == ["2.5", "2026-01-02", "5", "True", EMPTY_GROUP]
    assert [p.value for p in chart.points] == [1, 1, 1, 1, 1]


def test_huge_category_text_is_labelled_whole() -> None:
    long_text = "Б" * 5000
    rows = [_row("a", long_text), _row("b", "Ачаа")]
    chart = _build(rows)
    assert [p.label for p in chart.points] == ["Ачаа", long_text]


def test_decimal_overflow_average_is_none() -> None:
    huge = Decimal("1E+999999")
    rows = [_row("a", "X", pay=huge), _row("b", "X", pay=huge)]
    chart = _build(rows, _spec(value=(PAY, "avg")))
    assert chart.points[0].value is None


def test_whitespace_only_category_is_shown_as_blank_but_is_its_own_bucket() -> None:
    rows = [_row("Бат", "   "), _row("Номин", "   "), _row("Дорж", ""), _row("Оюу", "Ачаа")]
    chart = _build(rows)
    assert [(p.label, p.value) for p in chart.points] == [("Ачаа", 1), (EMPTY_GROUP, 2), (EMPTY_GROUP, 1)]
