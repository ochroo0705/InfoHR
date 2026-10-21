from datetime import date

import pytest
from accounts.models import User
from employees.services.macs_writes import ListEntryInUse
from macs.models import Employee, Entitlement, LeaveAssign, LeaveTypeRow, LegalHoliday

from leave.models import GrantKind, LeaveExt, LeaveTypeExt
from leave.services import writes
from leave.services.writes import CANCELLED_CLASH, DUPLICATE, STALE, AssignSnapshot, WriteConflict

pytestmark = pytest.mark.django_db

START = date(2026, 2, 17)
END = date(2026, 2, 19)


def _record(employee: Employee, leave_type: LeaveTypeRow, actor: User, comment: str = "Гэр бүл") -> LeaveAssign:
    return writes.record_assign(employee, leave_type, START, END, 3, comment, actor)


def test_record_inserts_and_ext(employee: Employee, annual: LeaveTypeRow, actor: User) -> None:
    a = _record(employee, annual, actor)
    row = LeaveAssign.objects.get(pk=a.pk)
    assert row.status == LeaveAssign.APPROVED
    assert row.adays == 3
    assert row.comment == "Гэр бүл"
    ext = LeaveExt.objects.get(assign=row)
    assert ext.created_by == actor
    assert ext.mistake is False


def test_record_reuses_cancelled_row(employee: Employee, annual: LeaveTypeRow, actor: User) -> None:
    a = _record(employee, annual, actor)
    loaded = writes.snapshot(a)
    writes.cancel_assign(a, loaded, "алдсан", mistake=True, by=actor)

    again = _record(employee, annual, actor, comment="дахин")

    assert again.pk == a.pk
    row = LeaveAssign.objects.get(pk=a.pk)
    assert row.status == LeaveAssign.APPROVED
    assert LeaveExt.objects.get(assign=row).mistake is False
    assert LeaveAssign.objects.filter(employee=employee, leave_type=annual).count() == 1


def test_record_duplicate_active_refused(employee: Employee, annual: LeaveTypeRow, actor: User) -> None:
    _record(employee, annual, actor)
    with pytest.raises(WriteConflict) as exc:
        _record(employee, annual, actor)
    assert str(exc.value) == DUPLICATE


def test_update_refused_when_row_changed(employee: Employee, annual: LeaveTypeRow, actor: User) -> None:
    a = _record(employee, annual, actor)
    loaded = writes.snapshot(a)
    # The old program changes the row after the user loaded it.
    LeaveAssign.objects.filter(pk=a.pk).update(comment="хуучин программ")

    with pytest.raises(WriteConflict) as exc:
        writes.update_assign(
            a,
            loaded,
            leave_type=annual,
            start=START,
            end=END,
            days=3,
            comment="шинэ",
            by=actor,
        )
    assert str(exc.value) == STALE
    assert LeaveAssign.objects.get(pk=a.pk).comment == "хуучин программ"


def test_cancel_mistake_flag(employee: Employee, annual: LeaveTypeRow, actor: User) -> None:
    a = _record(employee, annual, actor)
    writes.cancel_assign(a, writes.snapshot(a), "буруу оруулсан", mistake=True, by=actor)

    row = LeaveAssign.objects.get(pk=a.pk)
    assert row.status == LeaveAssign.CANCELLED
    ext = LeaveExt.objects.get(assign=row)
    assert ext.mistake is True
    assert ext.cancel_reason == "буруу оруулсан"


def test_delete_used_type_refused(employee: Employee, annual: LeaveTypeRow, actor: User) -> None:
    Entitlement.objects.create(
        employee=employee,
        leave_type=annual,
        date1=date(2026, 1, 1),
        date2=date(2026, 12, 31),
        ent_days=15,
    )
    with pytest.raises(ListEntryInUse):
        writes.delete_leave_type(annual)
    assert LeaveTypeRow.objects.filter(pk=annual.pk).exists()


def test_add_grant_writes_entitlement_and_ext(employee: Employee, annual: LeaveTypeRow, actor: User) -> None:
    grant = writes.add_grant(
        employee,
        annual,
        date(2026, 1, 1),
        date(2026, 12, 31),
        15,
        "2026 он",
        GrantKind.AUTO,
        actor,
        breakdown="15 хоног",
    )
    assert Entitlement.objects.get(pk=grant.pk).ent_days == 15
    assert LeaveTypeExt.objects.filter(pk=annual.pk).exists()


def test_save_and_delete_unused_type() -> None:
    row = writes.save_leave_type("Өвчний чөлөө", {"is_paid": True})
    assert LeaveTypeExt.objects.get(pk=row.pk).is_paid is True
    writes.delete_leave_type(row)
    assert not LeaveTypeRow.objects.filter(pk=row.pk).exists()
    assert not LeaveTypeExt.objects.filter(pk=row.pk).exists()


def test_holidays_run_merged() -> None:
    dates = {date(2026, 2, 17): "Цагаан сар", date(2026, 2, 18): "Цагаан сар", date(2026, 2, 19): "Цагаан сар"}
    writes.set_holiday_dates(2026, dates)

    rows = list(LegalHoliday.objects.filter(name="Цагаан сар"))
    assert len(rows) == 1
    assert rows[0].start_date == date(2026, 2, 17)
    assert rows[0].end_date == date(2026, 2, 19)
    assert rows[0].hdays == 3


def test_holidays_untouched_rows_kept() -> None:
    writes.set_holiday_dates(2026, {date(2026, 2, 17): "Цагаан сар"})
    kept = LegalHoliday.objects.get(name="Цагаан сар")

    writes.set_holiday_dates(
        2026,
        {date(2026, 2, 17): "Цагаан сар", date(2026, 5, 1): "Олон улсын хөдөлмөрийн баяр"},
    )

    assert LegalHoliday.objects.get(name="Цагаан сар").pk == kept.pk
    assert LegalHoliday.objects.filter(name="Олон улсын хөдөлмөрийн баяр", hdays=1).exists()


def _update(
    a: LeaveAssign,
    loaded: AssignSnapshot,
    leave_type: LeaveTypeRow,
    start: date,
    end: date,
    actor: User,
    comment: str = "шинэ",
) -> LeaveAssign:
    return writes.update_assign(
        a,
        loaded,
        leave_type=leave_type,
        start=start,
        end=end,
        days=3,
        comment=comment,
        by=actor,
        override_reason="засвар",
    )


def test_update_success(employee: Employee, annual: LeaveTypeRow, actor: User) -> None:
    a = _record(employee, annual, actor)
    loaded = writes.snapshot(a)
    new_start, new_end = date(2026, 3, 2), date(2026, 3, 4)

    row = _update(a, loaded, annual, new_start, new_end, actor)

    stored = LeaveAssign.objects.get(pk=a.pk)
    assert row.pk == a.pk
    assert stored.date1 == new_start
    assert stored.date2 == new_end
    assert stored.adays == 3
    assert stored.comment == "шинэ"
    assert stored.status == LeaveAssign.APPROVED
    assert LeaveExt.objects.get(assign=stored).override_reason == "засвар"


def test_update_clash_active_duplicate(employee: Employee, annual: LeaveTypeRow, actor: User) -> None:
    a = _record(employee, annual, actor)
    other = writes.record_assign(employee, annual, date(2026, 3, 2), date(2026, 3, 4), 3, "өөр", actor)
    before = LeaveAssign.objects.get(pk=other.pk).comment

    with pytest.raises(WriteConflict) as exc:
        _update(a, writes.snapshot(a), annual, date(2026, 3, 2), date(2026, 3, 4), actor)

    assert str(exc.value) == DUPLICATE
    assert LeaveAssign.objects.get(pk=other.pk).comment == before
    assert LeaveAssign.objects.get(pk=a.pk).date1 == START


def test_update_clash_cancelled_message(employee: Employee, annual: LeaveTypeRow, actor: User) -> None:
    a = _record(employee, annual, actor)
    other = writes.record_assign(employee, annual, date(2026, 3, 2), date(2026, 3, 4), 3, "цуцлагдсан", actor)
    writes.cancel_assign(other, writes.snapshot(other), "цуцалсан", mistake=False, by=actor)
    other_before = LeaveAssign.objects.get(pk=other.pk)
    a_before = LeaveAssign.objects.get(pk=a.pk)

    with pytest.raises(WriteConflict) as exc:
        _update(a, writes.snapshot(a), annual, date(2026, 3, 2), date(2026, 3, 4), actor)

    assert str(exc.value) == CANCELLED_CLASH
    other_after = LeaveAssign.objects.get(pk=other.pk)
    a_after = LeaveAssign.objects.get(pk=a.pk)
    assert (other_after.status, other_after.comment, other_after.date1) == (
        other_before.status,
        other_before.comment,
        other_before.date1,
    )
    assert (a_after.date1, a_after.comment) == (a_before.date1, a_before.comment)


def _stored_holiday(name: str, start: date, end: date) -> LegalHoliday:
    return LegalHoliday.objects.create(name=name, start_date=start, end_date=end, hdays=(end - start).days + 1)


def test_prefill_keeps_adjacent_old_rows() -> None:
    from leave.services import calendar

    first = _stored_holiday("Цагаан сар", date(2026, 2, 17), date(2026, 2, 17))
    second = _stored_holiday("Цагаан сар", date(2026, 2, 18), date(2026, 2, 18))

    calendar.prefill_year(2026)

    assert LegalHoliday.objects.get(pk=first.pk).end_date == date(2026, 2, 17)
    assert LegalHoliday.objects.get(pk=second.pk).start_date == date(2026, 2, 18)
    assert LegalHoliday.objects.filter(name="Цагаан сар").count() == 2


def test_prefill_keeps_renamed_old_row() -> None:
    from leave.services import calendar

    old = _stored_holiday("Эмэгтэйчүүдийн өдөр", date(2026, 3, 8), date(2026, 3, 8))

    calendar.prefill_year(2026)

    kept = LegalHoliday.objects.get(pk=old.pk)
    assert kept.name == "Эмэгтэйчүүдийн өдөр"
    assert kept.start_date == date(2026, 3, 8)


def test_cross_year_row_survives_other_year_edit() -> None:
    kept = _stored_holiday("Шинэ жил", date(2026, 12, 30), date(2027, 1, 2))

    writes.set_holiday_dates(2026, {date(2026, 12, 31): "Шинэ жил"})

    survivor = LegalHoliday.objects.get(name="Шинэ жил", start_date=date(2027, 1, 1))
    assert survivor.end_date == date(2027, 1, 2)
    assert survivor.hdays == 2
    assert survivor.pk == kept.pk
    assert LegalHoliday.objects.get(name="Шинэ жил", start_date=date(2026, 12, 31)).hdays == 1


def test_delete_one_day_from_multi_day_row_splits_only_that_row() -> None:
    _stored_holiday("Цагаан сар", date(2026, 2, 16), date(2026, 2, 20))
    other = _stored_holiday("Бусад", date(2026, 5, 1), date(2026, 5, 1))

    # `dates` is the whole year: every holiday day that should remain.
    dates = {date(2026, 2, n): "Цагаан сар" for n in (16, 17, 19, 20)}
    dates[date(2026, 5, 1)] = "Бусад"
    writes.set_holiday_dates(2026, dates)

    spans = sorted((row.start_date, row.end_date, row.hdays) for row in LegalHoliday.objects.filter(name="Цагаан сар"))
    assert spans == [(date(2026, 2, 16), date(2026, 2, 17), 2), (date(2026, 2, 19), date(2026, 2, 20), 2)]
    assert LegalHoliday.objects.get(pk=other.pk).name == "Бусад"


def test_record_reuses_rejected_row(employee: Employee, annual: LeaveTypeRow, actor: User) -> None:
    a = _record(employee, annual, actor)
    LeaveAssign.objects.filter(pk=a.pk).update(status=LeaveAssign.REJECTED)
    LeaveExt.objects.update_or_create(
        assign=a, defaults={"mistake": True, "cancel_reason": "татгалзсан", "created_by": actor}
    )

    again = _record(employee, annual, actor, comment="дахин")

    assert again.pk == a.pk
    row = LeaveAssign.objects.get(pk=a.pk)
    assert row.status == LeaveAssign.APPROVED
    assert row.comment == "дахин"
    ext = LeaveExt.objects.get(assign=row)
    assert ext.mistake is False
    assert ext.cancel_reason == ""
    assert LeaveAssign.objects.filter(employee=employee, leave_type=annual).count() == 1
