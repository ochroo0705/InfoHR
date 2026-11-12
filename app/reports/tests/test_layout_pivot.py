"""The pivot: rows by one category, columns by another, totals, blank «—», folding beyond 30 rows and 12 columns."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from reports import layouts as layouts_mod
from reports.filters import Filters
from reports.layouts import LayoutSpec, Pivot
from reports.table import EMPTY_GROUP, Table
from reports.types import Column

TODAY = date(2026, 11, 7)

NAME = Column(key="name", label="Нэр", value=lambda r: r.name, kind="text")
DEPT = Column(key="dept", label="Хэлтэс", value=lambda r: r.dept, kind="text")
LEVEL = Column(key="level", label="Түвшин", value=lambda r: r.level, kind="text")
PAY = Column(key="pay", label="Цалин", value=lambda r: r.pay, kind="number", numeric=True, money=True)


def _row(name: str | None, dept: object, level: object = "A", pay: object = 0) -> Any:
    return SimpleNamespace(name=name, dept=dept, level=level, pay=pay)


def _spec(
    value: tuple[Column | None, str] = (None, "count"), by2: Column | None = LEVEL, by: Column | None = DEPT
) -> LayoutSpec:
    return LayoutSpec(layout="pivot", by=by, by2=by2, value=value, chart="bar", month=date(2026, 11, 1))


def _build(rows: list[Any], spec: LayoutSpec | None = None) -> Pivot:
    spec = spec or _spec()
    table = Table(columns=[NAME, DEPT, LEVEL, PAY], groups=[], count=len(rows), filters=Filters(), rows=rows, spec=spec)
    return layouts_mod.build_pivot(table, spec)


def _rows() -> list[Any]:
    return [
        _row("Бат", "Санхүү", "A"),
        _row("Дорж", "Санхүү", "B"),
        _row("Оюу", "Ачаа", "A"),
        _row("Номин", "Ачаа", "A"),
        _row("Төмөр", "Ачаа", "C"),
        _row("Сараа", None, "B"),
    ]


def test_counts_by_department_and_level_with_totals_and_grand() -> None:
    rows = _rows()
    pivot = _build(rows)
    assert pivot.row_labels == ["Ачаа", "Санхүү", EMPTY_GROUP]
    assert pivot.col_labels == ["A", "B", "C"]
    assert pivot.cells == [[2, 0, 1], [1, 1, 0], [0, 1, 0]]
    assert pivot.row_totals == [3, 2, 1]
    assert pivot.col_totals == [3, 2, 1]
    assert pivot.grand == len(rows)
    assert pivot.money is False


def test_grand_equals_table_count() -> None:
    rows = _rows()
    table = Table(columns=[NAME], groups=[], count=len(rows), filters=Filters(), rows=rows, spec=_spec())
    pivot = layouts_mod.build_pivot(table, _spec())
    assert pivot.grand == table.count


def test_sum_of_pay_has_money_and_exact_totals(settings: Any) -> None:
    settings.REPORTS_MIN_GROUP = 1  # these tests check other things; the small-group rule has its own tests
    rows = [_row("Бат", "X", "A", Decimal("100.10")), _row("Дорж", "X", "B", Decimal("0.90"))]
    pivot = _build(rows, _spec(value=(PAY, "sum")))
    assert pivot.money is True
    assert pivot.cells == [[Decimal("100.10"), Decimal("0.90")]]
    assert pivot.grand == Decimal("101.00")


def test_avg_is_none_for_an_empty_bucket(settings: Any) -> None:
    settings.REPORTS_MIN_GROUP = 1  # these tests check other things; the small-group rule has its own tests
    rows = [_row("Бат", "X", "A", 10), _row("Дорж", "X", "A", 20), _row("Оюу", "Y", "B", 7)]
    pivot = _build(rows, _spec(value=(PAY, "avg")))
    assert pivot.row_labels == ["X", "Y"]
    assert pivot.cells[0][0] == 15
    assert pivot.cells[0][1] is None  # X has no B
    assert pivot.cells[1][0] is None  # Y has no A
    assert pivot.cells[1][1] == 7


def test_without_by2_there_is_one_column_named_total() -> None:
    rows = _rows()
    pivot = _build(rows, _spec(by2=None))
    assert pivot.col_labels == ["Нийт"]
    assert pivot.cells == [[row_total] for row_total in pivot.row_totals]
    assert pivot.grand == len(rows)


def test_fifteen_columns_fold_into_busad_after_twelve() -> None:
    rows = [_row(f"Нэр {i}", "X", f"L{i:02d}") for i in range(15)]
    pivot = _build(rows)
    assert len(pivot.col_labels) == 12
    assert pivot.col_labels[:11] == [f"L{i:02d}" for i in range(11)]
    assert pivot.col_labels[-1] == "Бусад"
    assert pivot.cells == [[1] * 11 + [4]]
    assert pivot.col_totals[-1] == 4
    assert pivot.grand == 15


def test_forty_rows_fold_into_busad_after_thirty() -> None:
    rows = [_row(f"Нэр {i}", f"D{i:02d}", "A") for i in range(40)]
    pivot = _build(rows)
    assert len(pivot.row_labels) == 30
    assert pivot.row_labels[-1] == "Бусад"
    assert pivot.row_totals[-1] == 11
    assert pivot.cells[-1] == [11]
    assert pivot.grand == 40


def test_folded_aggregate_is_recomputed_over_the_folded_rows() -> None:
    rows = [_row(f"Нэр {i}", f"D{i:02d}", "A", pay=i) for i in range(35)]
    pivot = _build(rows, _spec(value=(PAY, "sum")))
    assert pivot.row_totals[-1] == sum(range(29, 35))  # D29..D34 summed over their rows
    assert pivot.grand == sum(range(35))


def test_empty_rows_give_no_rows_and_zero_grand() -> None:
    pivot = _build([])
    assert pivot.row_labels == []
    assert pivot.col_labels == []
    assert pivot.cells == []
    assert pivot.grand == 0


def test_value_label_names_the_column_and_aggregate() -> None:
    assert _build(_rows()).value_label == "Тоо"
    assert "Цалин" in _build(_rows(), _spec(value=(PAY, "sum"))).value_label


def _pay_rows() -> list[Any]:
    return [
        _row("Бат", "X", "A", 10),
        _row("Дорж", "X", "B", 30),
        _row("Оюу", "X", "B", 50),
        _row("Номин", "Y", "A", 100),
    ]


def test_avg_row_and_column_totals_are_over_the_rows_not_the_cells(settings: Any) -> None:
    settings.REPORTS_MIN_GROUP = 1  # these tests check other things; the small-group rule has its own tests
    pivot = _build(_pay_rows(), _spec(value=(PAY, "avg")))
    assert pivot.row_labels == ["X", "Y"]
    assert pivot.col_labels == ["A", "B"]
    assert pivot.cells == [[10, 40], [100, None]]
    assert pivot.row_totals == [30, 100]  # (10 + 30 + 50) / 3, not the mean of the cells (10 + 40) / 2
    assert pivot.row_totals[0] != (10 + 40) / 2
    assert pivot.col_totals == [55, 40]  # (10 + 100) / 2 and (30 + 50) / 2
    assert pivot.grand == Decimal("47.50")


def test_min_row_and_column_totals_are_over_the_rows(settings: Any) -> None:
    settings.REPORTS_MIN_GROUP = 1  # these tests check other things; the small-group rule has its own tests
    pivot = _build(_pay_rows(), _spec(value=(PAY, "min")))
    assert pivot.row_totals == [10, 100]
    assert pivot.col_totals == [10, 30]
    assert pivot.grand == 10


def test_max_row_and_column_totals_are_over_the_rows(settings: Any) -> None:
    settings.REPORTS_MIN_GROUP = 1  # these tests check other things; the small-group rule has its own tests
    pivot = _build(_pay_rows(), _spec(value=(PAY, "max")))
    assert pivot.row_totals == [50, 100]
    assert pivot.col_totals == [100, 50]
    assert pivot.grand == 100


def test_folded_row_avg_total_is_the_average_of_the_folded_rows() -> None:
    rows = [_row(f"Нэр {i}", f"D{i:02d}", "A", pay=i) for i in range(35)]
    pivot = _build(rows, _spec(value=(PAY, "avg")))
    assert pivot.row_labels[-1] == "Бусад"
    assert pivot.row_totals[-1] == Decimal("31.50")  # (29 + ... + 34) / 6
    assert pivot.cells[-1] == [Decimal("31.50")]
    assert pivot.grand == Decimal("17.00")


def test_folded_column_avg_total_is_recomputed_over_the_folded_rows() -> None:
    rows = [_row(f"Нэр {i}", "X", f"L{i:02d}", pay=i) for i in range(15)]
    pivot = _build(rows, _spec(value=(PAY, "avg")))
    assert pivot.col_labels[-1] == "Бусад"
    assert pivot.col_totals[-1] == Decimal("12.50")  # (11 + 12 + 13 + 14) / 4
    assert pivot.cells[0][-1] == Decimal("12.50")


def test_decimal_overflow_average_is_none_in_a_cell_and_total() -> None:
    huge = Decimal("1E+999999")
    pivot = _build([_row("a", "X", "A", huge), _row("b", "X", "A", huge)], _spec(value=(PAY, "avg")))
    assert pivot.cells == [[None]]
    assert pivot.row_totals == [None]
    assert pivot.grand is None


def test_mixed_text_and_number_values_sum_only_the_numbers(settings: Any) -> None:
    settings.REPORTS_MIN_GROUP = 1  # these tests check other things; the small-group rule has its own tests
    rows = [_row("Бат", "X", "A", "n/a"), _row("Дорж", "X", "A", 5), _row("Оюу", "X", "B", Decimal("2.5"))]
    pivot = _build(rows, _spec(value=(PAY, "sum")))
    assert pivot.cells == [[5, Decimal("2.5")]]
    assert pivot.grand == Decimal("7.5")


def test_category_keys_of_any_type_are_labelled_without_error() -> None:
    rows = [_row("a", None, "A"), _row("b", 5, "A")]
    pivot = _build(rows)
    assert pivot.row_labels == ["5", EMPTY_GROUP]


def test_huge_row_label_is_kept_whole() -> None:
    long_text = "Б" * 5000
    pivot = _build([_row("a", long_text, "A"), _row("b", "Ачаа", "A")])
    assert pivot.row_labels == ["Ачаа", long_text]


def test_whitespace_only_row_key_is_shown_as_blank_but_is_its_own_row() -> None:
    rows = [_row("a", "Ачаа", "A"), _row("b", "  ", "A"), _row("c", "", "A")]
    pivot = _build(rows)
    assert pivot.row_labels == ["Ачаа", EMPTY_GROUP, EMPTY_GROUP]
    assert pivot.cells == [[1], [1], [1]]


def test_blank_pivot_column_key_sorts_last() -> None:
    rows = [_row("Бат", "X", None), _row("Дорж", "X", "L1"), _row("Оюу", "X", "A")]
    pivot = _build(rows)
    assert pivot.col_labels == ["A", "L1", EMPTY_GROUP]
    assert pivot.cells == [[1, 1, 1]]


def test_name_count_on_a_text_column_counts_rows() -> None:
    rows = [_row(None, "X", "A"), _row("Бат", "X", "A"), _row("", "X", "B")]
    pivot = _build(rows, _spec(value=(NAME, "count")))
    assert pivot.cells == [[2, 1]]
    assert pivot.grand == 3
