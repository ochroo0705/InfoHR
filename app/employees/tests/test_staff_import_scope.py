"""The data scope on the staff Excel import and on the employee edit form. A user limited to some branches imports
people only into those branches and picks a branch only from them; the edit form keeps an employee's current branch
even when it is outside the user's list. An unlimited user is unchanged."""

import io
from datetime import date
from typing import Any

import pytest
from accounts import roles
from accounts.models import AccessScope, User
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.test import Client
from django.urls import reverse
from macs.models import Branch
from openpyxl import Workbook

from employees.forms import EmployeeForm
from employees.models import Employee, StaffImportDraft
from employees.services import history
from employees.staff_import import plan
from employees.staff_import.matching import auto_match
from employees.staff_import.plan import OUT_OF_SCOPE
from employees.staff_import.run import run_import

from .conftest import hire_values
from .helpers import make_branch

pytestmark = pytest.mark.django_db

PASSWORD = "x-long-pass-123"  # noqa: S105
SHEET = "Ажилтан"
COLUMNS = (
    ("family_name", "Овог"),
    ("given_name", "Нэр"),
    ("register_no", "Регистр"),
    ("start", "Ажилд орсон огноо"),
    ("department", "Хэлтэс"),
    ("position", "Албан тушаал"),
    ("branch", "Салбар"),
)
HEADINGS = [heading for _, heading in COLUMNS]
BASE: dict[str, Any] = {
    "family_name": "Бат",
    "given_name": "Дорж",
    "register_no": "УБ99112244",
    "start": date(2026, 3, 1),
    "department": "Санхүү",
    "position": "Нягтлан",
}


def person(branch: str | None, **changes: Any) -> list[object]:
    cells = {**BASE, "branch": branch, **changes}
    return [cells.get(key) for key, _ in COLUMNS]


def workbook(rows: list[list[object]]) -> bytes:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = SHEET
    ws.append(HEADINGS)
    for row in rows:
        ws.append(row)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def make_draft(rows: list[list[object]], created_by: User | None = None) -> StaffImportDraft:
    return StaffImportDraft.objects.create(
        created_by=created_by,
        filename="staff.xlsx",
        data=workbook(rows),
        sheet=SHEET,
        header_rows=1,
        mapping=auto_match(HEADINGS, remembered={}, allow_salary=True),
        date_format="iso",
    )


def scoped_user(name: str, *branches: Branch, role: str | None = None) -> User:
    """A user whose data scope lists these branches. Returned fresh, so no cached permissions or scope."""
    user = User.objects.create_user(name, password=PASSWORD)  # noqa: S106
    AccessScope.objects.create(user=user, limited=True, branch_ids=[branch.pk for branch in branches])
    if role is not None:
        user.groups.add(Group.objects.get(name=role))
    return User.objects.get(pk=user.pk)


def hired_at(branch: Branch, register_no: str, actor: User, job: dict[str, Any]) -> Employee:
    values = {**hire_values(register_no), "family_name": "Гантулга", "given_name": "Болд"}
    employee = history.hire(values, {}, start=date(2026, 1, 5), job=dict(job), salary=None, by=actor)
    Employee.objects.filter(pk=employee.pk).update(branch_id=branch.pk)
    return Employee.objects.get(pk=employee.pk)


def test_row_outside_the_hirers_branches_is_refused_and_blank_takes_the_default() -> None:
    north, south = make_branch("Хойд"), make_branch("Өмнөд")
    hirer = scoped_user("hr_north", north)
    draft = make_draft(
        [
            person(north.name, register_no="УБ99112244"),
            person(south.name, register_no="УБ99112255", given_name="Сэрэн"),
            person(None, register_no="УБ99112266", given_name="Оюун"),
        ]
    )

    preview = plan.build_preview(draft, allow_salary=False, user=hirer)

    inside, outside, blank = preview.rows
    assert inside.status == "new"
    assert inside.values["branch_id"] == north.pk
    assert outside.status == "error"
    assert outside.errors == [OUT_OF_SCOPE]
    assert blank.status == "new"
    assert blank.values["branch_id"] == north.pk
    assert (preview.new, preview.errors) == (2, 1)


def test_unlimited_user_may_import_into_any_branch_and_blank_gets_none() -> None:
    south = make_branch("Өмнөд")
    unlimited = User.objects.create_user("hr_all", password=PASSWORD)  # noqa: S106
    draft = make_draft([person(south.name), person(None, register_no="УБ99112255", given_name="Сэрэн")])

    for user in (unlimited, None):
        preview = plan.build_preview(draft, allow_salary=False, user=user)
        assert [row.status for row in preview.rows] == ["new", "new"]
        assert preview.rows[0].values["branch_id"] == south.pk
        assert "branch_id" not in preview.rows[1].values


def test_run_creates_no_person_outside_the_hirers_branches() -> None:
    north, south = make_branch("Хойд"), make_branch("Өмнөд")
    hirer = scoped_user("hr_north", north)
    draft = make_draft(
        [
            person(north.name, register_no="УБ99112244"),
            person(south.name, register_no="УБ99112255", given_name="Сэрэн"),
        ]
    )

    run_import(draft, by=hirer, allow_salary=False)

    draft.refresh_from_db()
    assert draft.state == "imported"
    assert (draft.created_count, draft.rejected_count) == (1, 1)
    assert not Employee.objects.filter(given_name="Сэрэн").exists()
    assert Employee.objects.get(given_name="Дорж").branch_id == north.pk


def test_import_map_lists_only_the_hirers_branches(client: Client) -> None:
    north = make_branch("Хойд")
    make_branch("Өмнөд")
    hirer = scoped_user("hr_north", north, role=roles.HR)
    draft = make_draft([person(north.name)], created_by=hirer)
    client.force_login(hirer)

    response = client.get(reverse("employees:import_map", args=[draft.pk]))

    assert response.status_code == 200
    assert response.context["branches"] == ["Хойд"]


def test_edit_form_lists_the_hirers_branches_and_the_employees_current_one(
    actor: User, job_values: dict[str, Any]
) -> None:
    north, south, east = make_branch("Хойд"), make_branch("Өмнөд"), make_branch("Зүүн")
    employee = hired_at(east, "УБ99112277", actor, job_values)  # in the east, outside the hirer's list
    hirer = scoped_user("hr_north", north)

    form = EmployeeForm(employee=employee, user=hirer)

    shown = set(form.fields["branch"].queryset.values_list("pk", flat=True))  # type: ignore[attr-defined]
    assert shown == {north.pk, east.pk}
    assert south.pk not in shown
    assert form.fields["branch"].clean(str(east.pk)).pk == east.pk  # the stored value stays valid
    with pytest.raises(ValidationError):
        form.fields["branch"].clean(str(south.pk))  # a crafted value outside the list is refused


def test_edit_form_shows_every_branch_to_an_unlimited_user(actor: User, job_values: dict[str, Any]) -> None:
    north, south, east = make_branch("Хойд"), make_branch("Өмнөд"), make_branch("Зүүн")
    employee = hired_at(east, "УБ99112277", actor, job_values)

    for user in (actor, None):
        form = EmployeeForm(employee=employee, user=user)
        shown = set(form.fields["branch"].queryset.values_list("pk", flat=True))  # type: ignore[attr-defined]
        assert shown == {north.pk, south.pk, east.pk}


def test_duplicate_branch_name_resolves_to_the_listed_one() -> None:
    outside = make_branch("Хойд")  # created first, so a lookup over all branches would pick it
    listed = make_branch("Хойд")
    hirer = scoped_user("hr_dup_name", listed)
    draft = make_draft([person(listed.name)])

    row = plan.build_preview(draft, allow_salary=False, user=hirer).rows[0]

    assert row.status == "new"
    assert row.values["branch_id"] == listed.pk
    assert row.values["branch_id"] != outside.pk


def test_limited_user_whose_listed_branches_were_deleted_gets_branch_required() -> None:
    gone = make_branch("Хуучин")
    hirer = scoped_user("hr_gone", gone)
    Branch.objects.filter(pk=gone.pk).delete()  # the scope keeps the stale id: it matches no branch now
    draft = make_draft(
        [
            person(None, register_no="УБ99112244"),
            person("Хуучин", register_no="УБ99112255", given_name="Сэрэн"),
        ]
    )

    blank, named = plan.build_preview(draft, allow_salary=False, user=hirer).rows

    assert blank.status == "error"
    assert blank.errors == [plan.BRANCH_REQUIRED]
    assert named.status == "error"  # a name that exists nowhere is the usual unknown-value error
    assert named.errors and "олдсонгүй" in named.errors[0]
    assert "branch_id" not in named.values
