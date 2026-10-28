import re
from collections.abc import Callable

import pytest
from accounts.models import User
from django.test import Client
from django.utils import timezone
from macs.models import Department, PresentType

from reports.filters import Filters
from reports.registry import REPORTS
from reports.table import Table, build_table
from reports.types import Column, Report

pytestmark = pytest.mark.django_db


def test_unknown_report_is_404(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "HR")
    assert client.get("/reports/nope/").status_code == 404


def test_needs_permission(client: Client, login_as: Callable[..., User], fake_report: Report) -> None:
    login_as(client, "Employee")
    assert client.get("/reports/fake/").status_code == 403


def test_forbidden_columns_dropped_everywhere(
    client: Client, login_as: Callable[..., User], fake_report: Report
) -> None:
    user = login_as(client, "HR")  # HR: view_personal, no view_salary
    table = build_table(fake_report, user, Filters(columns=("name", "pay", "regno")))
    assert [c.key for c in table.columns] == ["name", "regno"]
    page = client.get("/reports/fake/?cols=name&cols=pay").content.decode()
    assert "Цалин" not in page  # label of `pay`


def test_sort_and_group(fake_report: Report, hr_user: User) -> None:
    table = build_table(
        fake_report,
        hr_user,
        Filters(columns=("name", "dept"), sort="-name", group="dept"),
    )
    assert [g for g, _ in table.groups] == ["Борлуулалт", "Санхүү", "Хэлтэсгүй"]  # empty group last
    assert table.count == 3


def test_garbage_query_renders_defaults(client: Client, login_as: Callable[..., User], fake_report: Report) -> None:
    login_as(client, "Admin")
    assert client.get("/reports/fake/?cols=zzz&sort=--x&group=pay&as_of=bad").status_code == 200


def test_htmx_request_returns_page_with_report_block(
    client: Client, login_as: Callable[..., User], fake_report: Report
) -> None:
    login_as(client, "HR")
    assert 'id="report-page"' in client.get("/reports/fake/", HTTP_HX_REQUEST="true").content.decode()


def _values(table: Table) -> list[object]:
    """The first column's raw values, in the order the table shows them."""
    return [row[0].value for _, rows in table.groups for row in rows]


def test_mixed_types_sort_both_ways_with_none_last(hr_user: User, mixed_report: Report) -> None:
    ascending = build_table(mixed_report, hr_user, Filters(columns=("v",), sort="v"))
    assert _values(ascending) == [1, 3, "", "abc", None]
    descending = build_table(mixed_report, hr_user, Filters(columns=("v",), sort="-v"))
    assert _values(descending) == ["abc", "", 3, 1, None]


def test_mixed_values_sort_on_the_page(client: Client, login_as: Callable[..., User], mixed_report: Report) -> None:
    login_as(client, "HR")
    page = client.get("/reports/mixed/?cols=v&sort=-v").content.decode()
    assert "<td>abc</td>" in page  # the rows reach the template, not just the header


def test_sort_by_name_descending(fake_report: Report, hr_user: User) -> None:
    table = build_table(fake_report, hr_user, Filters(columns=("name",), sort="-name"))
    assert _values(table) == ["Сараа", "Дорж", "Бат"]


def test_every_filter_has_a_label(
    client: Client, login_as: Callable[..., User], fake_all_filters_report: Report
) -> None:
    login_as(client, "HR")
    response = client.get("/reports/fake-all/")
    assert response.status_code == 200
    page = response.content.decode()
    for label in ("Төлөв", "Огноо", "Салбар", "Хэлтэс", "Албан тушаал", "Хүйс"):
        assert f'aria-label="{label}"' in page
    assert "Харах" in page  # the no-JS submit button


def test_untouched_date_box_sends_no_date(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "HR")
    page = client.get("/reports/staff-list/?department=1").content.decode()
    tag = re.search(r'<input[^>]*name="as_of"[^>]*>', page)
    assert tag is not None and ' value=""' in tag.group(0)


def test_filter_form_reloads_on_select_change_and_date_commit_only(client: Client, login_hr: User) -> None:
    page = client.get("/reports/staff-list/").content.decode()
    assert 'hx-trigger="change, submit"' in page


def test_department_without_name_shows_a_dash_in_the_filter(client: Client, login_hr: User) -> None:
    nameless = Department.objects.create(name=None)
    page = client.get("/reports/staff-list/?state=all").content.decode()
    assert f'<option value="{nameless.pk}">—</option>' in page
    assert ">None</option>" not in page


def test_period_and_new_filters_render_with_values(client: Client, login_hr: User, fake_period_report: Report) -> None:
    html = client.get(
        "/reports/fake-period/?from=2026-02-01&to=2026-03-31&change=termination&order_type=4&group=name"
    ).content.decode()
    assert 'name="from"' in html and 'value="2026-02-01"' in html and 'value="2026-03-31"' in html
    assert "Хугацаа" in html and "Бүх шалтгаан" in html and "Бүх ажилтан" in html
    assert '<option value="termination" selected>' in html
    assert '<option value="4" selected>' in html
    assert "Бүлэглэхгүй" in html and html.count('name="group"') == 1
    assert 'aria-label="Бүлэглэх"' in html


def test_period_inputs_show_this_year_by_default(client: Client, login_hr: User, fake_period_report: Report) -> None:
    year = timezone.localdate().year
    html = client.get("/reports/fake-period/").content.decode()
    assert f'value="{year}-01-01"' in html and f'value="{year}-12-31"' in html


def test_htmx_filter_change_pushes_clean_address(client: Client, login_hr: User) -> None:
    year = timezone.localdate().year
    url = f"/reports/movements/?from={year}-01-01&to={year}-12-31&branch=&change=hire"
    response = client.get(url, HTTP_HX_REQUEST="true")
    assert response["HX-Push-Url"] == (
        "/reports/movements/?change=hire&cols=day&cols=code&cols=name&cols=kind&cols=from_department"
        "&cols=department&cols=from_position&cols=position&cols=order"
    )


def test_plain_get_has_no_push_url(client: Client, login_hr: User) -> None:
    response = client.get("/reports/movements/?change=hire")
    assert not response.has_header("HX-Push-Url")


def _this_quarter() -> int:
    return (timezone.localdate().month - 1) // 3 + 1


@pytest.fixture
def fake_phase5_report(monkeypatch: pytest.MonkeyPatch) -> Report:
    """A report that declares the phase 5 filters (training type, quarter, gift type), registered as «fake-phase5»."""
    report = Report(
        key="fake-phase5",
        title="Улирал",
        filters=("tr_type", "quarter", "present_type"),
        columns=(Column(key="name", label="Нэр", value=lambda r: r.name),),
        default_columns=("name",),
        rows=lambda user, filters: [],
    )
    monkeypatch.setitem(REPORTS, "fake-phase5", report)
    return report


def test_phase5_filters_render_with_values(client: Client, login_hr: User, fake_phase5_report: Report) -> None:
    present = PresentType.objects.create(name="Номын бэлэг")
    html = client.get(f"/reports/fake-phase5/?tr_type=2&quarter=3&present_type={present.pk}").content.decode()
    assert 'aria-label="Хэлбэр"' in html and 'aria-label="Улирал"' in html and 'aria-label="Бэлгийн төрөл"' in html
    assert "Бүх хэлбэр" in html and "Бүх бэлэг" in html
    assert '<option value="2" selected>Гадаад</option>' in html
    assert '<option value="3" selected>3-р улирал</option>' in html
    assert f'<option value="{present.pk}" selected>Номын бэлэг</option>' in html


def test_phase5_quarter_defaults_to_this_quarter(client: Client, login_hr: User, fake_phase5_report: Report) -> None:
    html = client.get("/reports/fake-phase5/").content.decode()
    assert f'<option value="{_this_quarter()}" selected>' in html
