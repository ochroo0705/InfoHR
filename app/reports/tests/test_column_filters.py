import pytest
from accounts.models import User
from django.http import QueryDict
from macs.models import Nationality

from reports.column_filters import COLUMN_FILTERS, describe_extra, parse_extra
from reports.filters import Filters, describe, parse_filters, to_query
from reports.staff_list import COLUMNS
from reports.table import offered_column_filters, usable_filters
from reports.types import Column, Report

pytestmark = pytest.mark.django_db


def test_parse_extra_keeps_valid_pairs() -> None:
    extra = parse_extra(QueryDict("nationality=3&hired_from=2020-01-01&salary_to=2000000"))
    assert extra == (("nationality", "3"), ("hired_from", "2020-01-01"), ("salary_to", "2000000"))


def test_parse_extra_ignores_garbage() -> None:
    query = "hired_from=abc&nationality=-1&nationality=x&work_conditions=9&salary_to=99999999999999999999"
    assert parse_extra(QueryDict(query)) == ()


def test_round_trip_stable_order() -> None:
    shuffled = "salary_to=2000000&nationality=3&hired_from=2020-01-01&work_conditions=2"
    f = parse_filters(QueryDict(shuffled))
    assert f.extra == (
        ("nationality", "3"),
        ("work_conditions", "2"),
        ("hired_from", "2020-01-01"),
        ("salary_to", "2000000"),
    )
    assert to_query(parse_filters(QueryDict(to_query(f)))) == to_query(f)


def test_describe_extra_names_code_value() -> None:
    nationality = Nationality.objects.create(name="Монгол")
    lines = describe_extra((("nationality", str(nationality.pk)),))
    assert lines == [f"Үндэс угсаа: {nationality.name}"]


def test_describe_extra_unknown_id_reads_dash() -> None:
    assert describe_extra((("nationality", "987654"),)) == ["Үндэс угсаа: —"]


def test_describe_extra_range_and_choice() -> None:
    extra = (("work_conditions", "2"), ("salary_from", "1000000"), ("salary_to", "2000000"))
    assert describe_extra(extra) == ["Ажлын нөхцөл: Хүнд", "Үндсэн цалин: 1000000 – 2000000"]


def test_describe_appends_extra_lines() -> None:
    f = Filters(extra=(("work_conditions", "1"),))
    assert describe(f, ("state",))[-1] == "Ажлын нөхцөл: Хэвийн"


def test_registry_columns_exist() -> None:
    keys = {c.key for c in COLUMNS}
    for cf in COLUMN_FILTERS.values():
        assert cf.column in keys, cf.name


def test_registry_labels_match_columns() -> None:
    """The labels are copies of the staff-table column labels; a renamed column must fail here."""
    for cf in COLUMN_FILTERS.values():
        col = next(c for c in COLUMNS if c.key == cf.column)
        assert cf.label == col.label, cf.name


def _staff_like_report(column_filters: tuple[str, ...]) -> Report:
    """A report with a salary column (needs view_salary) and a hire date column (no permission needed)."""
    return Report(
        key="column-filter-test",
        title="Шүүлтүүр",
        filters=(),
        columns=(
            Column(key="salary", label="Үндсэн цалин", value=lambda r: None, needs="macs.view_salary"),
            Column(key="first_hire_date", label="Ажилд орсон", value=lambda r: None),
        ),
        default_columns=("first_hire_date",),
        rows=lambda user, filters: [],
        column_filters=column_filters,
    )


_EXTRA = (("salary_from", "1000000"), ("hired_from", "2020-01-01"), ("hired_to", "2021-01-01"))


def test_extras_dropped_without_column_permission(hr_user: User, accountant_user: User) -> None:
    report = _staff_like_report(("salary", "hired"))
    filters = Filters(extra=_EXTRA)
    assert usable_filters(report, hr_user, filters).extra == (("hired_from", "2020-01-01"), ("hired_to", "2021-01-01"))
    assert usable_filters(report, accountant_user, filters).extra == _EXTRA


def test_undeclared_extras_dropped(hr_user: User) -> None:
    report = _staff_like_report(())
    assert usable_filters(report, hr_user, Filters(extra=_EXTRA)).extra == ()


def test_offered_column_filters_skips_unknown_and_missing_columns(hr_user: User) -> None:
    report = _staff_like_report(("nope", "bank", "hired"))  # bank's column is not in this report
    assert offered_column_filters(report, hr_user) == ["hired"]
