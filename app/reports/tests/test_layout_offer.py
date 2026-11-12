"""Offered layouts, the layout columns each one uses, and per-viewer cleaning of the layout parameters."""

import inspect

import pytest
from accounts.models import User
from django.http import QueryDict
from django.utils import timezone

from reports import layouts as layouts_mod
from reports import leave_requests, staff_list
from reports.filters import Filters, parse_filters
from reports.layouts import clean_params, offered_layouts, resolve
from reports.table import restricted_filters
from reports.types import Column, Report

pytestmark = pytest.mark.django_db


def _report(layouts: tuple[str, ...], group_options: tuple[str, ...] = ("dept",)) -> Report:
    return Report(
        key="layout-offer",
        title="Тайлан",
        filters=(),
        columns=(
            Column(key="name", label="Нэр", value=lambda r: r.name),
            Column(key="dept", label="Хэлтэс", value=lambda r: r.dept),
            Column(key="start", label="Эхлэх", value=lambda r: r.start, kind="date"),
            Column(key="end", label="Дуусах", value=lambda r: r.end, kind="date"),
            Column(key="pay", label="Цалин", value=lambda r: r.pay, needs="macs.view_salary", numeric=True, money=True),
        ),
        default_columns=("name",),
        rows=lambda user, filters: [],
        group_options=group_options,
        layouts=layouts,
    )


ALL = ("board", "calendar", "timeline", "cards", "chart", "pivot")


def _filters(raw: str) -> Filters:
    return parse_filters(QueryDict(raw))


def test_offered_layouts_follow_the_declared_order_and_start_with_table(
    accountant_user: User,
) -> None:
    assert offered_layouts(_report(ALL), accountant_user) == ["table", *ALL]


def test_salary_hidden_from_a_viewer_does_not_remove_layouts_with_other_columns(hr_user: User) -> None:
    assert offered_layouts(_report(ALL), hr_user) == ["table", *ALL]


def test_a_category_only_available_with_salary_is_not_offered_to_hr(accountant_user: User, hr_user: User) -> None:
    """Board needs a category column; when the only one is salary-gated, HR gets no board. Chart and pivot also take
    a date column (Task 3), and this report's start and end dates are visible to HR, so HR gets those two."""
    report = _report(("board", "chart", "pivot", "calendar"), group_options=("pay",))
    assert offered_layouts(report, hr_user) == ["table", "calendar", "chart", "pivot"]
    assert offered_layouts(report, accountant_user) == ["table", "board", "calendar", "chart", "pivot"]


def test_report_without_layouts_offers_only_table(accountant_user: User) -> None:
    report = _report(())
    assert offered_layouts(report, accountant_user) == ["table"]
    assert resolve(report, accountant_user, _filters("layout=board")).layout == "table"


def test_chart_without_any_category_or_date_column_offers_only_table(accountant_user: User) -> None:
    """Chart needs a category or a date column (Task 3). A report with neither offers only the table."""
    report = Report(
        key="no-category",
        title="Тайлан",
        filters=(),
        columns=(Column(key="name", label="Нэр", value=lambda r: r.name),),
        default_columns=("name",),
        rows=lambda user, filters: [],
        layouts=("chart",),
    )
    assert offered_layouts(report, accountant_user) == ["table"]


def test_chart_needs_no_number_column(accountant_user: User) -> None:
    report = Report(
        key="text-only",
        title="Тайлан",
        filters=(),
        columns=(Column(key="dept", label="Хэлтэс", value=lambda r: r.dept),),
        default_columns=("dept",),
        rows=lambda user, filters: [],
        group_options=("dept",),
        layouts=("chart",),
    )
    assert offered_layouts(report, accountant_user) == ["table", "chart"]


def test_calendar_needs_a_date_column(accountant_user: User) -> None:
    report = Report(
        key="no-dates",
        title="Тайлан",
        filters=(),
        columns=(Column(key="name", label="Нэр", value=lambda r: r.name),),
        default_columns=("name",),
        rows=lambda user, filters: [],
        layouts=("calendar", "timeline"),
    )
    assert offered_layouts(report, accountant_user) == ["table"]


def test_resolve_keeps_a_salary_value_out_for_hr(hr_user: User) -> None:
    spec = resolve(_report(("chart",)), hr_user, _filters("layout=chart&lval=pay:sum"))
    assert spec.layout == "chart"
    assert spec.value == (None, "count")


def test_resolve_uses_the_salary_sum_for_a_user_with_the_permission(accountant_user: User) -> None:
    spec = resolve(_report(("chart",)), accountant_user, _filters("layout=chart&lval=pay:sum"))
    assert spec.value[0] is not None and spec.value[0].key == "pay"
    assert spec.value[1] == "sum"


def test_resolve_falls_back_to_the_first_category_when_the_asked_one_is_hidden(
    hr_user: User,
) -> None:
    report = _report(("board",), group_options=("pay", "dept"))
    spec = resolve(report, hr_user, _filters("layout=board&lby=pay"))
    assert spec.by is not None and spec.by.key == "dept"


def test_resolve_falls_back_to_table_for_a_layout_not_offered(accountant_user: User) -> None:
    spec = resolve(_report(("board",)), accountant_user, _filters("layout=calendar"))
    assert spec.layout == "table"


def test_restricted_filters_clears_a_hidden_salary_column_in_the_layout_keys(hr_user: User) -> None:
    f = _filters("layout=board&lby=pay&lby2=pay&lval=pay:sum")
    cleaned = restricted_filters(_report(ALL), hr_user, f)
    assert cleaned.lby == ""
    assert cleaned.lby2 == ""
    assert cleaned.lval == ""


def test_restricted_filters_clears_salary_lby_even_with_the_permission(accountant_user: User) -> None:
    """pay is neither a group option nor a date column, so it is no category for a layout, whoever sees it."""
    cleaned = restricted_filters(_report(ALL), accountant_user, _filters("layout=board&lby=pay"))
    assert cleaned.lby == ""


def test_restricted_filters_keeps_allowed_layout_columns(accountant_user: User) -> None:
    cleaned = restricted_filters(
        _report(ALL), accountant_user, _filters("layout=calendar&lby=start&lby2=end&lval=count")
    )
    assert (cleaned.lby, cleaned.lby2, cleaned.lval) == ("start", "end", "count")


def test_layouts_source_does_not_import_table() -> None:
    """table imports layouts, so layouts must not import table (no cycle). Checked on the source text."""
    source = inspect.getsource(layouts_mod)
    assert "from reports.table" not in source
    assert "import reports.table" not in source


def test_month_defaults_to_the_first_day_of_this_month(accountant_user: User) -> None:
    today = timezone.localdate()
    assert resolve(_report(("calendar",)), accountant_user, _filters("layout=calendar")).month == today.replace(day=1)


@pytest.mark.parametrize("text", ["9999-99", "0000-01", "2026-13", "1899-12", "garbage"])
def test_bad_month_falls_back_to_this_month(accountant_user: User, text: str) -> None:
    today = timezone.localdate()
    spec = resolve(_report(("calendar",)), accountant_user, Filters(layout="calendar", lmonth=text))
    assert spec.month == today.replace(day=1)


def test_calendar_with_a_text_column_as_start_falls_back_to_the_first_date(accountant_user: User) -> None:
    spec = resolve(_report(("calendar",)), accountant_user, _filters("layout=calendar&lby=name"))
    assert spec.by is not None and spec.by.key == "start"


@pytest.mark.parametrize("layout", ["chart", "pivot"])
@pytest.mark.parametrize("lval", ["start:min", "start:max", "start:sum", "start:avg"])
def test_date_column_with_min_max_sum_or_avg_falls_back_to_count(accountant_user: User, layout: str, lval: str) -> None:
    spec = resolve(_report((layout,)), accountant_user, _filters(f"layout={layout}&lval={lval}"))
    assert spec.value == (None, "count")


def test_date_column_with_count_keeps_the_column(accountant_user: User) -> None:
    spec = resolve(_report(("chart",)), accountant_user, _filters("layout=chart&lval=start:count"))
    assert spec.value[0] is not None and spec.value[0].key == "start"
    assert spec.value[1] == "count"


def test_chart_with_a_text_value_falls_back_to_count(accountant_user: User) -> None:
    spec = resolve(_report(("chart",)), accountant_user, _filters("layout=chart&lval=name:sum"))
    assert spec.value == (None, "count")


def test_pivot_ignores_a_hidden_second_column_and_uses_the_next_category(hr_user: User) -> None:
    report = _report(("pivot",), group_options=("dept", "pay"))
    spec = resolve(report, hr_user, _filters("layout=pivot&lby2=pay"))
    assert spec.by2 is None  # pay is hidden from HR, and dept is already the row


def test_second_column_choices_leave_out_the_main_column(accountant_user: User) -> None:
    report = _report(("pivot", "timeline"), group_options=("dept", "pay"))
    pivot = layouts_mod.layout_choices(report, accountant_user, "pivot", "dept")
    # Since Task 3 a pivot also takes the report's date columns, after the categories (start and end here)
    assert [k for k, _ in pivot.by] == ["dept", "pay", "start", "end"]
    assert [k for k, _ in pivot.by2] == ["pay", "start", "end"]
    timeline = layouts_mod.layout_choices(report, accountant_user, "timeline", "start")
    assert [k for k, _ in timeline.by2] == ["end"]


def test_timeline_ignores_a_hidden_end_column(hr_user: User) -> None:
    report = Report(
        key="tl",
        title="Тайлан",
        filters=(),
        columns=(
            Column(key="start", label="Эхлэх", value=lambda r: r.start, kind="date"),
            Column(key="pay", label="Цалин", value=lambda r: r.pay, kind="date", needs="macs.view_salary"),
        ),
        default_columns=("start",),
        rows=lambda user, filters: [],
        layouts=("timeline",),
    )
    spec = resolve(report, hr_user, _filters("layout=timeline&lby=start&lby2=pay&lyear=all"))
    assert spec.by is not None and spec.by.key == "start"
    assert spec.by2 is None


def test_clean_params_clears_an_lval_the_declared_kind_rules_out(accountant_user: User) -> None:
    cleaned = clean_params(_report(("chart",)), accountant_user, _filters("layout=chart&lval=dept:sum"))
    assert cleaned["lval"] == "dept:sum"  # dept is untyped: clean_params leaves it to resolve, which refuses the sum
    spec = resolve(_report(("chart",)), accountant_user, _filters("layout=chart&lval=dept:sum"))
    assert spec.value == (None, "count")
    report = _report(("chart",))
    cleaned_pay = clean_params(report, accountant_user, _filters("layout=chart&lval=pay:avg"))
    assert cleaned_pay["lval"] == "pay:avg"  # numeric declared kind allows avg


def test_clean_params_clears_min_on_a_text_declared_column(accountant_user: User) -> None:
    report = Report(
        key="typed",
        title="Тайлан",
        filters=(),
        columns=(Column(key="name", label="Нэр", value=lambda r: r.name, kind="text"),),
        default_columns=("name",),
        rows=lambda user, filters: [],
        group_options=("name",),  # a category, so the chart is offered and its layout keys are kept
        layouts=("chart",),
    )
    assert clean_params(report, accountant_user, _filters("layout=chart&lval=name:min"))["lval"] == ""
    assert clean_params(report, accountant_user, _filters("layout=chart&lval=name:count"))["lval"] == "name:count"


# ---- the default date columns (Report.layout_date and layout_date2) ----


def test_staff_list_calendar_defaults_to_first_hire_not_birth_date(hr_user: User) -> None:
    spec = resolve(staff_list.REPORT, hr_user, Filters(layout="calendar"))
    assert spec.by is not None and spec.by.key == "first_hire_date"


def test_staff_list_timeline_runs_from_first_hire_to_contract_end_not_birth_date(hr_user: User) -> None:
    spec = resolve(staff_list.REPORT, hr_user, Filters(layout="timeline", lyear="all"))
    assert spec.by is not None and spec.by.key == "first_hire_date"
    assert spec.by2 is not None and spec.by2.key == "contract_end"


def test_staff_list_default_is_not_birth_date_for_a_viewer_without_personal(accountant_user: User) -> None:
    spec = resolve(staff_list.REPORT, accountant_user, Filters(layout="timeline", lyear="all"))
    assert spec.by is not None and spec.by.key == "first_hire_date"


def test_explicit_lby_still_wins_over_the_report_default(hr_user: User) -> None:
    spec = resolve(staff_list.REPORT, hr_user, Filters(layout="calendar", lby="contract_end"))
    assert spec.by is not None and spec.by.key == "contract_end"


def test_leave_requests_timeline_defaults_to_start_and_end(hr_user: User) -> None:
    spec = resolve(leave_requests.REPORT, hr_user, Filters(layout="timeline", lyear="all"))
    assert spec.by is not None and spec.by.key == "start"
    assert spec.by2 is not None and spec.by2.key == "end"


def test_hidden_default_date_falls_back_to_the_first_allowed_date(hr_user: User) -> None:
    report = Report(
        key="layout-default-hidden",
        title="Тайлан",
        filters=(),
        columns=(
            Column(key="name", label="Нэр", value=lambda r: r.name),
            Column(
                key="pay_date",
                label="Цалингийн огноо",
                value=lambda r: r.pay_date,
                kind="date",
                needs="macs.view_salary",
            ),
            Column(key="start", label="Эхлэх", value=lambda r: r.start, kind="date"),
        ),
        default_columns=("name",),
        rows=lambda user, filters: [],
        layouts=("calendar",),
        layout_date="pay_date",
    )
    spec = resolve(report, hr_user, Filters(layout="calendar"))
    assert spec.by is not None and spec.by.key == "start"
