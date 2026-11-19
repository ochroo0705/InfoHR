"""GET /api/v1/employees/{pk}/work: the Work tab's display values, from employees.services.detail_page."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from accounts import roles
from accounts.models import AccessScope, User
from checklists.services import onboarding
from django.contrib.auth.models import Group
from django.test import Client
from django.utils import timezone
from employees import access as employee_access
from employees.models import (
    ChangeType,
    Employee,
    Event,
    EventType,
    HrOrder,
    JobRecord,
    LeaveKind,
    OrderState,
    OrderType,
)
from employees.services import history, macs_writes
from employees.tests.conftest import hire_values, link_login
from employees.tests.test_events import rec
from employees.views import ORDER_WARNING_KEY
from leave.models import GrantKind, LeaveSettings, LeaveTypeExt
from leave.services import writes as leave_writes
from macs.models import Branch, LeaveTypeRow, Office

from api.employee import _period_parts

pytestmark = pytest.mark.django_db

PASSWORD = "x-long-pass-123"  # noqa: S105
FUTURE = date(2030, 1, 1)


@pytest.fixture
def hr_user(db: None) -> User:
    user = User.objects.create_user("employee_work_hr", password=PASSWORD)
    user.groups.add(Group.objects.get_or_create(name=roles.HR)[0])
    return user


@pytest.fixture
def job_values(db: None) -> dict[str, Any]:
    return {
        "position": macs_writes.save_position("Нягтлан"),
        "department": macs_writes.save_department("Санхүү"),
        "employee_type": "full_time",
        "status": "active",
        "contract_type": "open_ended",
    }


@pytest.fixture
def hired(hr_user: User, job_values: dict[str, Any]) -> Employee:
    """A working employee hired on 2026-01-05."""
    return history.hire(
        hire_values(),
        {},
        start=date(2026, 1, 5),
        job=job_values,
        salary=Decimal("2500000"),
        by=hr_user,
        order_number="1",
        order_date=date(2026, 1, 5),
    )


def _client(user: User) -> Client:
    client = Client()
    client.force_login(user)
    return client


def test_scheduled_job_change_has_its_period_without_odoo(hr_user: User, hired: Employee) -> None:
    history.change_job(
        hired,
        effective=FUTURE,
        changes={"department": macs_writes.save_department("Маркетинг")},
        change_type=ChangeType.TRANSFER,
        note="Шилжүүлэв",
        by=hr_user,
    )
    body = _client(hr_user).get(f"/api/v1/employees/{hired.pk}/work").json()
    scheduled = [row for row in body["jobs"] if row["scheduled"]]
    assert len(scheduled) == 1
    assert scheduled[0]["period_text"].startswith("2030-01-01 –")
    assert "одоо" not in scheduled[0]["period_text"]
    assert scheduled[0]["period_note"] == ""
    assert scheduled[0]["is_cancelled"] is False


def test_long_leave_note_is_its_own_field_and_open_rows_say_odoo() -> None:
    """The template prints «(… буцна)» in a grey span and « одоо» as plain text; the API sends them apart."""
    leave = SimpleNamespace(
        is_cancelled=False,
        period=SimpleNamespace(lower=date(2026, 1, 5), upper=None),
        status="long_leave",
        event=SimpleNamespace(expected_return=date(2026, 8, 1)),
        scheduled=False,
    )
    assert _period_parts(leave) == ("2026-01-05 –", "(2026-08-01 буцна)")
    open_row = SimpleNamespace(
        is_cancelled=False,
        period=SimpleNamespace(lower=date(2026, 1, 5), upper=None),
        status="active",
        event=None,
        scheduled=False,
    )
    assert _period_parts(open_row) == ("2026-01-05 – одоо", "")
    cancelled = SimpleNamespace(is_cancelled=True, effective=date(2026, 3, 1))
    assert _period_parts(cancelled) == ("2026-03-01", "")


def test_leave_block_is_hidden_without_the_leave_right(hired: Employee) -> None:
    viewer = User.objects.create_user("employee_work_plain", password=PASSWORD)
    link_login(hired, viewer)  # the own record is visible; no leave right is granted
    body = _client(viewer).get(f"/api/v1/employees/{hired.pk}/work").json()
    assert body["leave"]["visible"] is False
    assert body["leave"]["periods"] == []
    assert body["leave"]["nowhere"] == []


def test_work_outside_the_scope_is_404(hr_user: User, hired: Employee) -> None:
    AccessScope.objects.create(user=hr_user, limited=True)  # a limited scope with no branch, department or team
    assert _client(hr_user).get(f"/api/v1/employees/{hired.pk}/work").status_code == 404


def test_unknown_pk_is_404(hr_user: User) -> None:
    assert _client(hr_user).get("/api/v1/employees/999999/work").status_code == 404


def test_order_warning_comes_once_and_is_not_cached(hr_user: User, hired: Employee) -> None:
    client = _client(hr_user)
    session = client.session
    session[ORDER_WARNING_KEY] = "Энэ дугаар MACS-д бүртгэлтэй байна."
    session.save()
    first = client.get(f"/api/v1/employees/{hired.pk}/work")
    assert first.json()["order_warning"] == "Энэ дугаар MACS-д бүртгэлтэй байна."
    assert "no-store" in first["Cache-Control"]
    second = client.get(f"/api/v1/employees/{hired.pk}/work")
    assert second.json()["order_warning"] == ""
    assert ORDER_WARNING_KEY not in client.session


def test_hr_sees_the_contract_and_macs_fields(hr_user: User, hired: Employee) -> None:
    Employee.objects.filter(pk=hired.pk).update(taken_leave=None)  # an unknown MACS value shows «—»
    body = _client(hr_user).get(f"/api/v1/employees/{hired.pk}/work").json()
    assert body["can_manage"] is True
    assert body["contract_end_label"] == "Хугацаагүй"
    assert body["macs_taken_leave"] == "—"
    assert body["jobs"][0]["order_no"].startswith("№ 1")


def test_first_hire_date_is_sent_only_to_managers(hr_user: User, hired: Employee) -> None:
    hire = _client(hr_user).get(f"/api/v1/employees/{hired.pk}/work").json()["first_hire_date"]
    assert hire == {
        "name": "first_hire_date",
        "kind": "date",
        "value": "2026-01-05",
        "choice": "",
        "combo": False,
        "text": "2026-01-05",
        "aria_label": "Анх ажилд орсон огноо",
    }
    viewer = User.objects.create_user("employee_work_hire_plain", password=PASSWORD)
    link_login(hired, viewer)
    assert _client(viewer).get(f"/api/v1/employees/{hired.pk}/work").json()["first_hire_date"] is None


def test_soft_fields_carry_their_widget_kind_raw_value_and_option_label(hr_user: User, hired: Employee) -> None:
    body = _client(hr_user).get(f"/api/v1/employees/{hired.pk}/work").json()
    assert body["sector_years"]["kind"] == "number"
    assert body["probation_end"]["kind"] == "date"
    for name in ("second_position", "office", "section", "branch", "work_schedule", "job_type", "job_figure"):
        field = body[name]
        assert field["kind"] == "select", name
        # An empty select keeps the empty value and an empty option text (Django's blank label is empty).
        assert (field["value"] == "") == (field["choice"] == ""), name
        assert field["combo"] is (name in ("second_position", "office", "section", "branch", "work_schedule")), name
    assert body["work_conditions"]["kind"] == "select"
    assert body["work_conditions"]["combo"] is False
    # The accessible names are the form field labels (Django's), not the row texts.
    assert body["office"]["aria_label"] == "Алба"
    assert body["branch"]["aria_label"] == "Салбар"
    assert body["work_schedule"]["aria_label"] == "Ажлын цагийн хуваарь"
    assert body["probation_end"]["aria_label"] == "Туршилтын хугацаа дуусах"
    assert body["sector_years"]["aria_label"] == "Салбарт ажилласан жил"


def test_seeded_branch_office_and_position_send_the_stored_option(hr_user: User, hired: Employee) -> None:
    """The soft values are the stored foreign keys: the branch and office the row holds; empty ones stay blank."""
    branch = Branch.objects.create(name="Төв салбар")
    office = Office.objects.create(name="program")
    Employee.objects.filter(pk=hired.pk).update(branch=branch, office=office)
    body = _client(hr_user).get(f"/api/v1/employees/{hired.pk}/work").json()
    assert body["position"] == "Нягтлан"
    assert body["department"] == "Санхүү"
    assert body["branch"] == {
        "name": "branch",
        "kind": "select",
        "value": str(branch.pk),
        "choice": "Төв салбар",
        "combo": True,
        "text": "Төв салбар",
        "aria_label": "Салбар",
    }
    assert body["office"]["value"] == str(office.pk)
    assert body["office"]["choice"] == "program"
    assert body["second_position"]["value"] == ""
    assert body["second_position"]["choice"] == ""
    assert body["second_position"]["text"] == "—"


def test_job_rows_send_clickable_and_the_grey_dash_as_flags(hr_user: User, hired: Employee) -> None:
    body = _client(hr_user).get(f"/api/v1/employees/{hired.pk}/work").json()
    for row in body["jobs"]:
        assert row["clickable"] == (row["order_pk"] is not None)
        assert row["order_no_muted"] == (row["order_no"] == "—")
        if row["is_cancelled"]:
            assert row["cancellable"] is False


def test_job_row_carries_event_id_of_its_change(hr_user: User, hired: Employee) -> None:
    event = rec(hired, hr_user, "leave_start", date(2026, 2, 1), reason=LeaveKind.values[0])
    body = _client(hr_user).get(f"/api/v1/employees/{hired.pk}/work").json()
    leave_job = JobRecord.objects.get(employee=hired, event=event)
    row = next(r for r in body["jobs"] if r["pk"] == leave_job.pk)
    assert row["event_id"] == event.pk
    for r in body["jobs"]:
        if r["pk"] is not None:  # the initial hire job: the model's own event_id (what the template's «Цуцлах» reads)
            assert r["event_id"] == JobRecord.objects.get(pk=r["pk"]).event_id


def test_long_leave_sends_its_note_as_its_own_field(hr_user: User, hired: Employee) -> None:
    rec(hired, hr_user, "leave_start", date(2026, 2, 1), reason=LeaveKind.values[0], expected_return=date(2026, 8, 1))
    body = _client(hr_user).get(f"/api/v1/employees/{hired.pk}/work").json()
    leave = [row for row in body["jobs"] if row["period_note"]]
    assert len(leave) == 1
    assert leave[0]["period_note"] == "(2026-08-01 буцна)"
    assert leave[0]["period_text"] == "2026-02-01 –"


def test_hr_gets_a_leave_period_with_its_badge_and_tone(hr_user: User, hired: Employee) -> None:
    annual = LeaveTypeRow.objects.create(name="Ээлжийн амралт")
    LeaveTypeExt.objects.create(leave_type=annual, uses_annual_balance=True, is_paid=True)
    LeaveSettings.objects.update_or_create(pk=1, defaults={"auto_annual_grant": False})
    leave_writes.add_grant(hired, annual, date(2026, 1, 5), date(2026, 12, 31), 15, "", GrantKind.AUTO, None)
    body = _client(hr_user).get(f"/api/v1/employees/{hired.pk}/work").json()
    leave = body["leave"]
    assert leave["visible"] is True
    assert leave["configured"] is True
    assert leave["no_year_started"] is False
    assert len(leave["periods"]) == 1
    period = leave["periods"][0]
    assert period["badge"]["label"] == "Одоо"
    assert period["current"] is True and period["old"] is False
    assert period["left"] == "15"
    assert "bg-emerald-100 text-emerald-800" in period["left_tone"]
    assert "bg-amber-50/60" in period["row_class"] and period["period_class"] == "font-semibold"
    assert leave["fold_old"] is False and leave["old_count"] == 0
    assert leave["fold_show_label"] == "" and leave["fold_hide_label"] == ""


def _old_year(start: date, end: date, *, current: bool = False, left: Decimal = Decimal("0")) -> SimpleNamespace:
    """A leave period as detail_facts returns it, with no grants or leaves."""
    return SimpleNamespace(
        start=start,
        end=end,
        current=current,
        upcoming=False,
        left=left,
        granted=Decimal("15"),
        taken=Decimal("0"),
        doubled=False,
        grants=[],
        leaves=[],
    )


def test_old_years_fold_with_their_labels_through_the_api(
    hr_user: User, hired: Employee, monkeypatch: pytest.MonkeyPatch
) -> None:
    import api.employee as api_employee

    original = api_employee.detail_facts

    def with_two_years(user: User, employee: Employee, today: date) -> dict[str, Any]:
        facts = original(user, employee, today)
        facts["leave_visible"] = True
        facts["leave_configured"] = True
        facts["leave_periods"] = [
            _old_year(date(2024, 1, 5), date(2024, 12, 31)),
            _old_year(date(2026, 1, 5), date(2026, 12, 31), current=True, left=Decimal("15")),
        ]
        return facts

    monkeypatch.setattr(api_employee, "detail_facts", with_two_years)
    leave = _client(hr_user).get(f"/api/v1/employees/{hired.pk}/work").json()["leave"]
    assert leave["fold_old"] is True and leave["old_count"] == 1
    assert leave["fold_show_label"] == "Өмнөх 1 жил харах ▾"
    assert leave["fold_hide_label"] == "Өмнөх жилүүдийг нуух ▴"
    assert [p["old"] for p in leave["periods"]] == [True, False]


def test_onboarding_panel_rows_split_the_done_label(hr_user: User, hired: Employee) -> None:
    onboarding.start_for_hire(hired, start_date=date(2026, 1, 5), employee_type="full_time", by=hr_user)
    body = _client(hr_user).get(f"/api/v1/employees/{hired.pk}/work").json()
    assert body["checklist_visible"] is True
    panel = next(p for p in body["checklists"] if p["kind"] == "onboarding")
    assert panel["checklist"] is True
    assert panel["progress"].endswith(f" / {len(panel['rows'])}")
    assert panel["rows"]
    open_row = panel["rows"][0]
    assert open_row["done"] is False
    assert open_row["done_label"] == "" and open_row["done_rest"] == "—"
    assert open_row["title_class"] == ""
    assert date.fromisoformat(panel["today"])


def test_order_row_flags_and_scan_url_follow_the_scan_right(hr_user: User, hired: Employee) -> None:
    # An order no change row claims, so it sits in «Бусад тушаал».
    event = Event.objects.create(
        employee=hired, type=EventType.PROMOTION, effective=date(2026, 2, 1), applied_at=timezone.now()
    )
    order = HrOrder.objects.create(
        employee=hired,
        event=event,
        order_type=OrderType.POSITION,
        state=OrderState.REGISTERED,
        number="7",
        date=date(2026, 2, 1),
        summary="Тест тушаал",
        file="2026/other-order.pdf",
    )
    body = _client(hr_user).get(f"/api/v1/employees/{hired.pk}/work").json()
    assert body["orders_count"] == len(body["orders"])
    row = next(r for r in body["orders"] if r["order_pk"] == order.pk)
    assert row["legacy"] is False
    assert row["can_edit"] is True
    assert (row["scan_url"] != "") is employee_access.can_open_order_scan(hr_user, order)
    if row["scan_url"]:
        assert row["scan_url"] == f"/api/v1/employees/{hired.pk}/orders/{order.pk}/file"
    viewer = User.objects.create_user("employee_work_order_plain", password=PASSWORD)
    link_login(hired, viewer)
    plain = _client(viewer).get(f"/api/v1/employees/{hired.pk}/work").json()
    plain_row = next(r for r in plain["orders"] if r["order_pk"] == order.pk)
    assert plain_row["can_edit"] is False
    assert (plain_row["scan_url"] != "") is employee_access.can_open_order_scan(viewer, order)


def test_order_urls_are_api_paths_and_empty_when_hidden(hr_user: User, hired: Employee) -> None:
    event = Event.objects.create(
        employee=hired, type=EventType.PROMOTION, effective=date(2026, 2, 1), applied_at=timezone.now()
    )
    order = HrOrder.objects.create(
        employee=hired,
        event=event,
        order_type=OrderType.POSITION,
        state=OrderState.REGISTERED,
        number="8",
        date=date(2026, 2, 1),
        summary="Замын тушаал",
        file="2026/url-order.pdf",
    )
    cancelled_event = Event.objects.create(
        employee=hired, type=EventType.PROMOTION, effective=date(2026, 3, 1), applied_at=timezone.now()
    )
    cancelled = HrOrder.objects.create(
        employee=hired,
        event=cancelled_event,
        order_type=OrderType.POSITION,
        state=OrderState.CANCELLED,
        number="9",
        date=date(2026, 3, 1),
        summary="Цуцалсан тушаал",
        file="",
    )
    base = f"/api/v1/employees/{hired.pk}/orders/{order.pk}"
    body = _client(hr_user).get(f"/api/v1/employees/{hired.pk}/work").json()
    rows = {r["order_pk"]: r for r in body["orders"]}
    row = rows[order.pk]
    # The scan and the documents each show only when their rule allows; a shown link is the API path.
    assert employee_access.can_open_order_scan(hr_user, order) and employee_access.can_manage(hr_user)
    assert row["scan_url"] == f"{base}/file"
    assert row["word_url"] == f"{base}/document"
    assert row["pdf_url"] == f"{base}/document/pdf"
    cancelled_row = rows[cancelled.pk]
    assert cancelled_row["scan_url"] == ""
    assert cancelled_row["word_url"] == ""
    assert cancelled_row["pdf_url"] == ""
    viewer = User.objects.create_user("employee_work_url_plain", password=PASSWORD)
    link_login(hired, viewer)
    plain_body = _client(viewer).get(f"/api/v1/employees/{hired.pk}/work").json()
    plain_row = next(r for r in plain_body["orders"] if r["order_pk"] == order.pk)
    assert plain_row["word_url"] == ""
    assert plain_row["pdf_url"] == ""


def test_cancelled_order_sends_its_cancel_text_as_segments_and_a_muted_number(hr_user: User, hired: Employee) -> None:
    event = Event.objects.create(
        employee=hired, type=EventType.PROMOTION, effective=date(2026, 2, 1), applied_at=timezone.now()
    )
    HrOrder.objects.create(
        employee=hired,
        event=event,
        order_type=OrderType.POSITION,
        state=OrderState.CANCELLED,
        number="",
        date=date(2026, 2, 1),
        summary="Цуцлагдсан тушаал",
        cancel_order_no="9",
    )
    body = _client(hr_user).get(f"/api/v1/employees/{hired.pk}/work").json()
    row = next(r for r in body["orders"] if r["summary"] == "Цуцлагдсан тушаал")
    assert row["number_muted"] is True
    assert row["cancel_prefix"] == "(цуцлах тушаал: "
    assert row["cancel_number"] == "№ 9"
    assert row["cancel_suffix"] == ")"
    assert row["cancelled"] is True


def test_cancelled_order_links_to_the_order_that_cancelled_it(hr_user: User, hired: Employee) -> None:
    def order(number: str, day: date, state: str, cancel_no: str, summary: str) -> HrOrder:
        event = Event.objects.create(employee=hired, type=EventType.PROMOTION, effective=day, applied_at=timezone.now())
        return HrOrder.objects.create(
            employee=hired,
            event=event,
            order_type=OrderType.POSITION,
            state=state,
            number=number,
            number_key=number,
            date=day,
            summary=summary,
            cancel_order_no=cancel_no,
        )

    canceller = order("5", date(2026, 2, 1), OrderState.REGISTERED, "", "Цуцлах тушаал")
    cancelled = order("6", date(2026, 2, 2), OrderState.CANCELLED, "5", "Цуцлагдсан тушаал")
    body = _client(hr_user).get(f"/api/v1/employees/{hired.pk}/work").json()
    gone = next(r for r in body["orders"] if r["order_pk"] == cancelled.pk)
    assert gone["cancelled_by_pk"] == canceller.pk
    assert gone["cancel_number"] == "№ 5"
    assert (gone["cancel_prefix"], gone["cancel_suffix"]) == ("(цуцлах тушаал: ", ")")
    who = next(r for r in body["orders"] if r["order_pk"] == canceller.pk)
    assert who["cancelled_by_pk"] is None
    assert [c["order_pk"] for c in who["cancels"]] == [cancelled.pk]
    assert who["cancels"][0]["link_text"] == "харах"


WORK_SOFT_FIELDS = (
    "second_position",
    "office",
    "section",
    "branch",
    "probation_end",
    "first_hire_date",
    "job_type",
    "job_figure",
    "work_conditions",
    "work_schedule",
    "sector_years",
)


def test_work_soft_fields_carry_their_form_names_that_page_form_has(hr_user: User, hired: Employee) -> None:
    body = _client(hr_user).get(f"/api/v1/employees/{hired.pk}/work").json()
    page = _client(hr_user).get(f"/api/v1/employees/{hired.pk}/page-form").json()
    form_names = {field["name"] for field in page["fields"]}
    for key in WORK_SOFT_FIELDS:
        assert body[key] is not None, key
        assert body[key]["name"] == key
        assert body[key]["name"] in form_names
