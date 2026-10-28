from datetime import timedelta
from decimal import Decimal

import pytest
from accounts.models import User
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from macs.models import FiredReason

from employees.models import Employee, Event, Position
from employees.services import events

from .conftest import link_login, named
from .helpers import record_signed
from .test_views import login_as

pytestmark = pytest.mark.django_db


def url(emp: Employee, type: str) -> str:
    return f"/employees/{emp.pk}/event/{type}/"


def tomorrow_plus() -> str:
    return (timezone.localdate() + timedelta(days=30)).isoformat()


def promote_data(emp: Employee, **extra: object) -> dict[str, object]:
    job = emp.job_records.get()
    new = Position.objects.create(name="Ахлах нягтлан")
    return {
        "effective": tomorrow_plus(),
        "position": new.pk,
        "department": job.department_id,
        "manager": "",
        "reason": "",
        "note": "",
        **extra,
    }


def schedule(emp: Employee, actor: User, **kw: object) -> Event:
    new = Position.objects.create(name="Ахлах")
    args: dict[str, object] = {"changes": {"position": new}, "salary": None, "reason": "", "note": "", "by": actor}
    args.update(kw)
    return record_signed(
        emp,
        type="promotion",
        effective=timezone.localdate() + timedelta(days=30),
        **args,
    )


def test_menu_per_role(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    body = client.get(f"/employees/{hired.pk}/").content.decode()
    assert "Өөрчлөлт бүртгэх" in body and "/event/transfer/" in body and "/event/salary_change/" not in body
    login_as(client, "Accountant", "acc")
    body = client.get(f"/employees/{hired.pk}/").content.decode()
    assert "/event/salary_change/" in body and "/event/transfer/" not in body


def test_employee_has_no_menu_and_cannot_open_form(client: Client, hired: Employee) -> None:
    link_login(hired, login_as(client, "Employee", "me"))
    hired.save()
    assert "Өөрчлөлт бүртгэх" not in client.get(f"/employees/{hired.pk}/").content.decode()
    assert client.get(url(hired, "promotion")).status_code == 403


def test_hr_form_has_no_salary_field_accountant_form_does(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    assert 'name="salary"' not in client.get(url(hired, "promotion")).content.decode()
    assert client.get(url(hired, "salary_change")).status_code == 403
    login_as(client, "Accountant", "acc")
    assert client.get(url(hired, "salary_change")).status_code == 200
    assert client.get(url(hired, "promotion")).status_code == 403


def test_form_prefills_values_in_force_and_warns(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    body = client.get(url(hired, "promotion") + "?effective=2026-03-01").content.decode()
    assert "Өнгөрсөн огноо — түүх засагдана" in body
    body = client.get(url(hired, "promotion") + f"?effective={tomorrow_plus()}&note=hello").content.decode()
    assert "Төлөвлөсөн" in body and "hello" in body and "Нягтлан" in body


def test_unknown_type_404(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    assert client.get(url(hired, "bogus")).status_code == 404


def test_post_promotion_schedules(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    response = client.post(url(hired, "promotion"), promote_data(hired))
    assert response.status_code == 204 and response["HX-Refresh"] == "true"
    assert Event.objects.get().type == "promotion"
    body = client.get(f"/employees/{hired.pk}/").content.decode()
    assert "Ажлын түүхээс харах, цуцлах" in body and "Цуцлах" in body


def test_post_termination_and_leave(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    data = {"effective": "2026-03-01", "reason": "maternity", "note": ""}
    assert client.post(url(hired, "leave_start"), data).status_code == 204
    data = {"effective": tomorrow_plus(), "fired_reason": named(FiredReason, "Өөрийн хүсэлтээр").pk, "note": ""}
    assert client.post(url(hired, "termination"), data).status_code == 204
    assert Event.objects.count() == 2


def test_post_salary_change_by_accountant(client: Client, hired: Employee) -> None:
    login_as(client, "Accountant", "acc")
    data = {"effective": tomorrow_plus(), "salary": "3000000", "reason": "", "note": ""}
    assert client.post(url(hired, "salary_change"), data).status_code == 204
    assert hired.salary_records.get(base_salary=Decimal("3000000"))


def test_hr_posting_salary_is_ignored(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    assert client.post(url(hired, "promotion"), promote_data(hired, salary="9000000")).status_code == 204
    assert not hired.salary_records.filter(base_salary=Decimal("9000000")).exists()


def test_validation_error_rerenders(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    data = promote_data(hired, position=hired.job_records.get().position_id)
    body = client.post(url(hired, "promotion"), data).content.decode()
    assert "Албан тушаал өөрчлөгдөөгүй байна." in body
    assert Event.objects.count() == 0


def test_summary_fragment(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    data = promote_data(hired)
    body = client.get(
        url(hired, "promotion"), {**{k: str(v) for k, v in data.items()}, "summary": "1"}
    ).content.decode()
    assert "Нягтлан → Ахлах нягтлан" in body and "<html" not in body


def test_cancel_scheduled(client: Client, hired: Employee, actor: User) -> None:
    event = schedule(hired, actor)
    login_as(client, "HR")
    cancel = f"/employees/{hired.pk}/event/{event.pk}/cancel/"
    assert client.get(cancel).status_code == 200
    assert client.post(cancel, {"reason": " "}).status_code == 200  # form re-renders, nothing cancelled
    assert client.post(cancel, {"reason": "алдаа", "cancel_order_no": "А/60"}).status_code == 204
    event.refresh_from_db()
    assert event.cancelled_at is not None


def test_cancel_forbidden_for_hr_on_mixed_event(client: Client, hired: Employee, actor: User) -> None:
    event = schedule(hired, actor, salary=Decimal("3100000"))
    login_as(client, "HR")
    assert client.get(f"/employees/{hired.pk}/event/{event.pk}/cancel/").status_code == 403
    assert client.post(f"/employees/{hired.pk}/event/{event.pk}/cancel/", {"reason": "x"}).status_code == 403
    login_as(client, "Accountant", "acc")
    assert client.get(f"/employees/{hired.pk}/event/{event.pk}/cancel/").status_code == 403


def test_scheduled_badge_in_tables(client: Client, hired: Employee, actor: User) -> None:
    schedule(hired, actor, salary=Decimal("3100000"))
    login_as(client, "HR")
    body = client.get(f"/employees/{hired.pk}/").content.decode()
    assert "Дэвшүүлэх" in body and "Төлөвлөсөн" in body  # badge in the history table
    assert "3 100 000" not in body


def test_own_page_event_without_salary_or_note(client: Client, hired: Employee, actor: User) -> None:
    schedule(hired, actor, salary=Decimal("3100000"), note="нууц тайлбар")
    link_login(hired, login_as(client, "Employee", "me"))
    hired.save()
    body = client.get(f"/employees/{hired.pk}/").content.decode()
    assert "Дэвшүүлэх" in body
    assert "3 100 000" not in body and "3100000" not in body and "нууц тайлбар" not in body
    assert "Цуцлах" not in body


def test_scheduled_rows_cannot_be_corrected(client: Client, hired: Employee, actor: User) -> None:
    schedule(hired, actor, salary=Decimal("3100000"))
    job = hired.job_records.get(event__isnull=False)
    sal = hired.salary_records.get(event__isnull=False)
    login_as(client, "HR")
    body = client.get(f"/employees/{hired.pk}/").content.decode()
    assert f"/job/{job.pk}/correct/" not in body
    assert client.get(f"/employees/{hired.pk}/job/{job.pk}/correct/").status_code == 403
    login_as(client, "Accountant", "acc")
    assert client.get(f"/employees/{hired.pk}/salary/{sal.pk}/correct/").status_code == 403


def test_accountant_sees_cancel_and_badge_on_salary_row(client: Client, hired: Employee, actor: User) -> None:
    events.record(
        hired,
        type="salary_change",
        effective=timezone.localdate() + timedelta(days=30),
        changes={},
        salary=Decimal("3100000"),
        reason="",
        note="",
        by=actor,
    )
    login_as(client, "Accountant", "acc")
    body = client.get(f"/employees/{hired.pk}/").content.decode()
    assert "Цуцлах" in body and "Төлөвлөсөн" in body
    sal = hired.salary_records.get(event__isnull=False)
    assert f"/salary/{sal.pk}/correct/" not in body


def test_header_hides_scheduled_salary_change_without_view_salary(client: Client, hired: Employee, actor: User) -> None:
    events.record(
        hired,
        type="salary_change",
        effective=timezone.localdate() + timedelta(days=10),
        changes={},
        salary=Decimal("3100000"),
        reason="",
        note="",
        by=actor,
    )
    schedule(hired, actor)
    login_as(client, "HR")
    body = client.get(f"/employees/{hired.pk}/").content.decode()
    assert "Ажлын түүхээс харах, цуцлах" in body and "Цалин өөрчлөх" not in body and "Дэвшүүлэх" in body
    link_login(hired, login_as(client, "Employee", "me"))
    hired.save()
    assert "Цалин өөрчлөх" not in client.get(f"/employees/{hired.pk}/").content.decode()


def test_cancel_of_effective_event_is_404(client: Client, hired: Employee, actor: User) -> None:
    new = Position.objects.create(name="Ахлах")
    event = record_signed(
        hired,
        type="promotion",
        effective=timezone.localdate() - timedelta(days=5),
        changes={"position": new},
        salary=None,
        reason="",
        note="",
        by=actor,
    )
    login_as(client, "HR")
    assert client.get(f"/employees/{hired.pk}/event/{event.pk}/cancel/").status_code == 404


def test_hr_salary_param_ignored_and_error_page_has_no_salary(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    data = promote_data(hired, position=hired.job_records.get().position_id, salary="9000000")
    body = client.post(url(hired, "promotion"), data).content.decode()
    assert 'name="salary"' not in body and "9000000" not in body
    assert hired.salary_records.count() == 1


def test_summary_forbidden_for_employee_and_accountant_on_job_type(client: Client, hired: Employee) -> None:
    link_login(hired, login_as(client, "Employee", "me"))
    hired.save()
    assert client.get(url(hired, "promotion"), {"summary": "1"}).status_code == 403
    login_as(client, "Accountant", "acc")
    assert client.get(url(hired, "promotion"), {"summary": "1"}).status_code == 403


def test_unchanged_prefilled_salary_creates_no_salary_record(client: Client, hired: Employee) -> None:
    login_as(client, "Accountant", "acc")
    assert (
        client.post(url(hired, "salary_change"), {"effective": tomorrow_plus(), "salary": "2500000"}).status_code == 200
    )
    login_as(client, "Admin", "adm")
    data = promote_data(hired, salary="2500000")
    assert client.post(url(hired, "promotion"), data).status_code == 204
    assert hired.salary_records.count() == 1


def test_menu_matches_current_state(client: Client, hired: Employee, actor: User) -> None:
    login_as(client, "HR")
    page = reverse("employees:detail", args=[hired.pk])
    body = client.get(page).content.decode()
    assert "/event/rehire/" not in body and "/event/leave_return/" not in body
    assert "/event/leave_start/" in body and "/event/termination/" in body
    record_signed(
        hired,
        type="termination",
        effective=timezone.localdate(),
        changes={},
        salary=None,
        reason="",
        fired_reason=named(FiredReason, "Өөрийн хүсэлтээр"),
        note="",
        by=actor,
    )
    body = client.get(page).content.decode()
    assert "/event/rehire/" in body and "/event/transfer/" not in body and "/event/termination/" not in body


def test_changing_date_keeps_edited_fields_and_refills_untouched(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    job = hired.job_records.get()
    data = promote_data(hired, reason="Сайн ажилласан", prev_effective=tomorrow_plus())
    data["effective"] = (timezone.localdate() + timedelta(days=40)).isoformat()
    html = client.get(url(hired, "promotion"), {k: str(v) for k, v in data.items()}).content.decode()
    assert f'<option value="{data["position"]}" selected' in html  # edited: kept
    assert f'<option value="{job.department_id}" selected' in html  # untouched: refilled
    assert "Сайн ажилласан" in html
    assert f'name="prev_effective" value="{data["effective"]}"' in html


def test_rebuilt_form_keeps_typed_order_fields(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    data = promote_data(hired, prev_effective=tomorrow_plus())
    data.update({"order-number": "Б/77", "order-summary": "Тушаалын агуулга", "order-issued_by": "Захирал Дорж"})
    html = client.get(url(hired, "promotion"), {k: str(v) for k, v in data.items()}).content.decode()
    assert 'value="Б/77"' in html and 'value="Тушаалын агуулга"' in html and 'value="Захирал Дорж"' in html
    assert "no-anim" in html
    first = client.get(url(hired, "promotion"), {"order-number": "Б/77"}).content.decode()
    assert 'value="Б/77"' not in first and "no-anim" not in first  # a fresh open ignores stray values


def test_placement_events_share_one_menu_item_and_a_type_choice(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    body = client.get(f"/employees/{hired.pk}/").content.decode()
    assert "Албан тушаал, байршил өөрчлөх" in body
    assert "/event/promotion/" not in body and "/event/demotion/" not in body
    html = client.get(url(hired, "promotion")).content.decode()
    assert "Албан тушаал, байршил өөрчлөх" in html and 'name="kind"' in html
    for kind in ("transfer", "promotion", "demotion"):
        assert f'value="{url(hired, kind)}"' in html
    assert f'value="{url(hired, "promotion")}" selected' in html
    assert 'name="kind"' not in client.get(url(hired, "termination")).content.decode()


def test_work_tab_shows_how_each_field_changes(client: Client, hired: Employee) -> None:
    """UI_RULES §2e: soft boxes for on-the-spot fields, an «өөрчлөх» chip for fields changed by an event."""
    login_as(client, "HR")
    body = client.get(f"/employees/{hired.pk}/").content.decode()
    assert body.count('title="Өөрчлөлт бүртгэж солино') == 4  # position, department, manager, contract
    assert body.count(f'hx-get="{url(hired, "transfer")}" hx-target="#modal" title=') == 3
    assert "f-soft" in body
    login_as(client, "Accountant", name="accountant")
    page = client.get(f"/employees/{hired.pk}/").content.decode()
    body = page[page.index('id="tab-work"') : page.index('id="tab-salary"')]  # the accountant edits bank fields there
    assert "f-soft" not in body and 'title="Өөрчлөлт бүртгэж солино' not in body


def test_leave_form_has_expected_return_and_header_shows_it(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    assert 'name="expected_return"' in client.get(url(hired, "leave_start")).content.decode()
    assert 'name="expected_return"' not in client.get(url(hired, "termination")).content.decode()
    today = timezone.localdate()
    back = (today + timedelta(days=200)).isoformat()
    data = {"effective": today.isoformat(), "reason": "childcare", "note": "", "expected_return": back}
    client.post(url(hired, "leave_start"), data)
    assert str(Event.objects.get(employee=hired, type="leave_start").expected_return) == back
    assert f"Урт чөлөөтэй · {back} хүртэл" in client.get(f"/employees/{hired.pk}/").content.decode()


def test_open_period_shows_now_only_once_started_and_planned_return(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    start = timezone.localdate() + timedelta(days=1)
    back = start + timedelta(days=5)
    data = {"effective": start.isoformat(), "reason": "unpaid", "note": "", "expected_return": back.isoformat()}
    client.post(url(hired, "leave_start"), data)
    html = client.get(f"/employees/{hired.pk}/").content.decode()
    assert f'{start:%Y-%m-%d} – <span class="text-slate-500">({back:%Y-%m-%d} буцна)</span>' in html
    assert f"{start:%Y-%m-%d} – одоо" not in html


def test_past_waiting_change_is_not_the_next_event(client: Client, hired: Employee, actor: User) -> None:
    login_as(client, "HR")
    past = timezone.localdate() - timedelta(days=10)
    lead = Position.objects.create(name="Ахлах нягтлан")
    event = events.record(
        hired, type="promotion", effective=past, changes={"position": lead}, salary=None,
        reason="", note="", by=actor,
    )  # fmt: skip
    assert event.applied_at is None
    body = client.get(f"/employees/{hired.pk}/").content.decode()
    assert "Ажлын түүхээс харах, цуцлах" not in body
