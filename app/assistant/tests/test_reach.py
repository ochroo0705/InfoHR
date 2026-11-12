"""Reach checks: the role lists match the real users, every entry opens, and every label is on a screen."""

from collections.abc import Callable
from datetime import date, timedelta

import pytest
from accounts.models import User
from checklists.models import ChecklistKind, ChecklistTemplate, ChecklistTemplateTask
from checklists.services import lifecycle
from django.contrib.auth.models import Group, Permission
from django.http import QueryDict
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from employees.models import (
    CompanySettings,
    Employee,
    EmployeeExt,
    Event,
    EventType,
    HrOrder,
    JobRecord,
    OrderTemplate,
    SalaryRecord,
)
from employees.services import macs_writes, orders, personal_writes, slots
from employees.slot_kind import MAIN
from leave.models import LeaveSettings, LeaveTypeExt
from leave.services import records as leave_records
from leave.services import requests as request_service
from leave.services.records import Draft
from macs.models import Branch, FamilyRelation, LeaveTypeRow, MaritalStatus
from recruitment.models import Candidate, RecruitmentSettings
from recruitment.services import pipeline
from reports import registry
from reports.filters import parse_filters, to_query
from reports.models import SavedView
from reports.table import build_table

from assistant.entries import ENTRIES, ENTRY_BY_KEY, allowed_entries
from assistant.evalset import ROLE_ENTRIES, ROLES
from assistant.models import HelpQuestion, Outcome
from assistant.tests.conftest import PASSWORD, ROLE_SETUP, TODAY
from assistant.tests.helpers import (
    hire_one,
    left,
    new_candidate,
    on_long_leave,
    on_screen,
    open_vacancy,
    scheduled_salary_change,
    scheduled_transfer,
)

pytestmark = pytest.mark.django_db

PAIRS = [(entry.key, role) for role in ROLES for entry in ENTRIES]


def _skip_unless_offered(key: str, role: str) -> None:
    """The role lists are built from the real rules (ROLE_ENTRIES), so a pair the role is not offered is skipped."""
    if key not in ROLE_ENTRIES[role]:
        pytest.skip(f"{key} is not offered to {role}")


def _set_approval(on: bool) -> None:
    LeaveSettings.objects.update_or_create(pk=1, defaults={"approval1_manager": on})


def _client(user: User) -> Client:
    client = Client()
    client.force_login(user)
    return client


def _page(client: Client, url: str, modal: bool) -> str:
    headers = {"HX-Request": "true"} if modal else {}
    resp = client.get(url, headers=headers, follow=True)  # a one-row settings list redirects to its form
    assert resp.status_code == 200, url
    return resp.content.decode()


# Extra pages for a label that is not on the entry's own page: a person's page in the needed state, or a pop-up.
# Each returns the bodies to search (the entry's page itself is always searched).
ExtraPages = Callable[[Client, Callable[[str], User]], list[str]]


def _attention_today(client: Client, role_user: Callable[[str], User]) -> list[str]:
    """A new hire is in onboarding with no emergency contact: the «Анхаарах» box lists them for HR-date users. A
    second hire's contract ends in 10 days: a dated item, which shows the visible «Мэдлээ» button (the name chips
    of undated items show only «×», with «Мэдлээ» in an aria-label)."""
    actor = role_user("hr")
    hire_one(actor)
    dated = hire_one(actor)
    JobRecord.objects.filter(employee=dated).update(contract_end=timezone.localdate() + timedelta(days=10))
    return [_page(client, reverse("employees:today"), False)]


def _person_page(client: Client, role_user: Callable[[str], User]) -> list[str]:
    """A new hire's employee page (onboarding not done, no login yet)."""
    person = hire_one(role_user("hr"))
    return [_page(client, reverse("employees:detail", args=[person.pk]), False)]


def _login_popup(client: Client, role_user: Callable[[str], User]) -> list[str]:
    """A new hire's page and the «Нэвтрэх эрх үүсгэх» pop-up (the page's button opens it with HX-Request)."""
    person = hire_one(role_user("hr"))
    return [
        _page(client, reverse("employees:detail", args=[person.pk]), False),
        _page(client, reverse("employees:login_create", args=[person.pk]), True),
    ]


def _list_page(client: Client, role_user: Callable[[str], User]) -> list[str]:
    """The employee list, where the «+ Ажилтан нэмэх» and «Ажилтан импортлох» buttons are."""
    return [_page(client, reverse("employees:list"), False)]


def _personal_row_pages(client: Client, role_user: Callable[[str], User]) -> list[str]:
    """A family row of a new hire: the person's page (the «Гэр бүл» list and «+ нэмэх») and that row open for editing,
    which is where «Устгах» is."""
    actor = role_user("hr")
    person = hire_one(actor)
    relation = FamilyRelation.objects.create(name="Хүү", fm_type="son")
    values = {"relation_id": relation.pk, "given_name": "Болд", "surname": "Бат", "job": "Багш"}
    key = personal_writes.add("family", person, values, {}, actor)
    return [
        _page(client, reverse("employees:detail", args=[person.pk]), False),
        _page(client, reverse("employees:personal_edit", args=[person.pk, "family", key]) + "?inline=1", False),
        # A pop-up list's add form (the «Хамаатан садан» pop-up) shows the visible «Хадгалах» and «Болих» buttons.
        _page(client, reverse("employees:personal_add", args=[person.pk, "relative"]), True),
    ]


def _nothing(actor: User, person: Employee) -> None:
    """Nothing to arrange: a working employee, the state a new hire is in."""


def _change_pages(event_type: str, arrange: Callable[[User, Employee], None] = _nothing) -> ExtraPages:
    """A person in the needed state: the employee page (the «Өөрчлөлт бүртгэх» menu is on it) and the pop-up of one
    change, which the menu item opens with HX-Request."""

    def pages(client: Client, role_user: Callable[[str], User]) -> list[str]:
        actor = role_user("hr")
        person = hire_one(actor)
        arrange(actor, person)
        return [
            _page(client, reverse("employees:detail", args=[person.pk]), False),
            _page(client, reverse("employees:event", args=[person.pk, event_type]), True),
        ]

    return pages


def _first_salary_pages(client: Client, role_user: Callable[[str], User]) -> list[str]:
    """A person with no salary yet: the salary tab offers «Цалин тогтоох», whose pop-up is the first-salary form."""
    person = hire_one(role_user("hr"), salary=None)
    return [
        _page(client, reverse("employees:detail", args=[person.pk]), False),
        _page(client, reverse("employees:set_salary", args=[person.pk]), True),
    ]


def _correct_job_pages(client: Client, role_user: Callable[[str], User]) -> list[str]:
    """The hire row of a new hire: the Ажил tab's «Засвар» pop-up."""
    person = hire_one(role_user("hr"))
    record = JobRecord.objects.get(employee=person)
    return [
        _page(client, reverse("employees:detail", args=[person.pk]), False),
        _page(client, reverse("employees:correct_job", args=[person.pk, record.pk]), True),
    ]


def _correct_salary_pages(client: Client, role_user: Callable[[str], User]) -> list[str]:
    """The hire salary row of a new hire: the salary tab's «Засвар» pop-up."""
    person = hire_one(role_user("hr"))
    record = SalaryRecord.objects.get(employee=person)
    return [
        _page(client, reverse("employees:detail", args=[person.pk]), False),
        _page(client, reverse("employees:correct_salary", args=[person.pk, record.pk]), True),
    ]


def _cancel_pages(client: Client, role_user: Callable[[str], User]) -> list[str]:
    """A scheduled job change and a scheduled salary change. The Ажил tab shows the job change's «Цуцлах» and its
    pop-up; the salary change is cancelled on the «Цалин, даатгал» tab, which only a user with salary rights sees, so
    that page is fetched as the Accountant."""
    actor = role_user("hr")
    person = hire_one(actor)
    scheduled_transfer(actor, person)
    scheduled_salary_change(actor, person)
    event = Event.objects.get(employee=person, type=EventType.TRANSFER)
    return [
        _page(client, reverse("employees:detail", args=[person.pk]), False),
        _page(_client(role_user("accountant")), reverse("employees:detail", args=[person.pk]), False),
        _page(client, reverse("employees:event_cancel", args=[person.pk, event.pk]), True),
    ]


def _hire_order(actor: User, *, registered: bool) -> tuple[Employee, HrOrder]:
    """A new hire and the hire order the hire made: pending (no number yet), or registered with number 15."""
    person = hire_one(actor)
    order = HrOrder.objects.get(employee=person, is_hire=True)
    if registered:
        order = orders.register(order, number="15", date=date(2026, 1, 5), summary="Ажилд авав", issued_by="", by=actor)
    return person, order


def _order_popups(registered: bool, *names: str) -> ExtraPages:
    """The pop-up of a hire order (`employees:order_detail`) and the pop-ups of the actions named here. All of them
    take the same (employee, order) arguments and open with HX-Request, as the register's rows and buttons do."""

    def pages(client: Client, role_user: Callable[[str], User]) -> list[str]:
        person, order = _hire_order(role_user("hr"), registered=registered)
        urls = [reverse(name, args=[person.pk, order.pk]) for name in ("employees:order_detail", *names)]
        return [_page(client, url, True) for url in urls]

    return pages


def _offboarding_on() -> None:
    """Switch the offboarding template on (the test settings switch every template off, as the employee tests do)."""
    ChecklistTemplate.objects.filter(kind=ChecklistKind.OFFBOARDING).update(active=True)


def _start_pages(client: Client, role_user: Callable[[str], User]) -> list[str]:
    """A working employee with no offboarding list yet: the Ажил tab's start panel with its «Ажлаас гарах жагсаалт эхлүүлэх» form."""
    _offboarding_on()
    person = hire_one(role_user("hr"))
    return [_page(client, reverse("employees:detail", args=[person.pk]), False)]


def _open_offboarding_pages(client: Client, role_user: Callable[[str], User]) -> list[str]:
    """An open offboarding list with one task ticked: the ticked row's «Буцаах» and the panel's «Цуцлах»."""
    actor = role_user("hr")
    _offboarding_on()
    person = hire_one(actor)
    checklist = lifecycle.start(person, ChecklistKind.OFFBOARDING, reason=None, anchor_day=TODAY, by=actor)
    assert checklist is not None
    task = checklist.tasks.first()
    assert task is not None
    lifecycle.tick(task, by=actor)
    return [_page(client, reverse("employees:detail", args=[person.pk]), False)]


def _template_pages(client: Client, role_user: Callable[[str], User]) -> list[str]:
    """An offboarding template with one task: its change page, whose task rows (inline) show «Хариуцах» and
    «Хугацаа (өдөр)»."""
    template = ChecklistTemplate.objects.create(kind=ChecklistKind.OFFBOARDING, name="Тест загвар")
    ChecklistTemplateTask.objects.create(template=template, title="Тест даалгавар", manager=True)
    return [_page(client, reverse("admin:checklists_checklisttemplate_change", args=[template.pk]), False)]


def _vacancy_list_page(client: Client, role_user: Callable[[str], User]) -> list[str]:
    """The vacancy list, where «Ажлын байр нээх» and «Хуучин татгалзсан…» buttons are for a manager."""
    return [_page(client, reverse("recruitment:vacancies"), False)]


def _vacancy_pages(popup: str = "") -> ExtraPages:
    """An open vacancy's page (the «Засах», «Ажил хүсэгчид» and «Шатаар шүүх» parts), and the pop-up `popup` for that
    vacancy when one is named (the vacancy's edit or add-candidate form)."""

    def pages(client: Client, role_user: Callable[[str], User]) -> list[str]:
        vacancy = open_vacancy(role_user("hr"))
        bodies = [_page(client, reverse("recruitment:vacancy_detail", args=[vacancy.pk]), False)]
        if popup:
            bodies.append(_page(client, reverse(popup, args=[vacancy.pk]), True))
        return bodies

    return pages


def _candidate_pages(popup: str = "", *, closed: bool = False) -> ExtraPages:
    """An open vacancy with one candidate (rejected when `closed`): the vacancy page and the candidate page, and the
    pop-up `popup` for the candidate when one is named (the reject form)."""

    def pages(client: Client, role_user: Callable[[str], User]) -> list[str]:
        actor = role_user("hr")
        vacancy = open_vacancy(actor)
        candidate = new_candidate(actor, vacancy)
        if closed:
            pipeline.reject(candidate, by=actor, reason="Туршлага хүрэлцэхгүй")
        bodies = [
            _page(client, reverse("recruitment:vacancy_detail", args=[vacancy.pk]), False),
            _page(client, reverse("recruitment:candidate_detail", args=[candidate.pk]), False),
        ]
        if popup:
            bodies.append(_page(client, reverse(popup, args=[candidate.pk]), True))
        return bodies

    return pages


def _purge_page(client: Client, role_user: Callable[[str], User]) -> list[str]:
    """A candidate rejected three years ago: the purge list has a row, so its «Устгах» button shows."""
    actor = role_user("hr")
    candidate = new_candidate(actor, open_vacancy(actor))
    pipeline.reject(candidate, by=actor, reason="Туршлага хүрэлцэхгүй")
    Candidate.objects.filter(pk=candidate.pk).update(closed_at=timezone.now() - timedelta(days=3 * 365))
    return [_page(client, reverse("recruitment:purge"), False)]


def _staff_list_page(client: Client, role_user: Callable[[str], User]) -> list[str]:
    """The staff list report: «Хэвлэх», «Excel» (export right) and «Багана» (the column picker)."""
    return [_page(client, reverse("reports:report", args=["staff-list"]), False)]


def _saved_view_pages(client: Client, role_user: Callable[[str], User]) -> list[str]:
    """A saved view of the staff list with the default setup, made by the signed-in user (so its «Засах» shows), and
    that view's pop-up, which holds «Устгах»."""
    user = User.objects.get(pk=client.session["_auth_user_id"])
    query = to_query(build_table(registry.REPORTS["staff-list"], user, parse_filters(QueryDict(""))).filters)
    view = SavedView.objects.create(report="staff-list", name="Тест харагдац", query=query, author=user)
    return [
        _page(client, reverse("reports:report", args=["staff-list"]) + "?" + query, False),  # the saved view selected
        _page(client, reverse("reports:view_edit", args=[view.pk]), True),
    ]


def _list_entry_pages(client: Client, role_user: Callable[[str], User]) -> list[str]:
    """A list with one entry: the list page with «Нэмэх», the add pop-up («Хадгалах») and the entry's edit pop-up,
    which holds «Устгах»."""
    row = MaritalStatus.objects.create(name="Тест")
    return [
        _page(client, reverse("lists:list", args=["marital_status"]), False),
        _page(client, reverse("lists:add", args=["marital_status"]), True),
        _page(client, reverse("lists:edit", args=["marital_status", row.pk]), True),
    ]


def _slot_pages(client: Client, role_user: Callable[[str], User]) -> list[str]:
    """The position-slot plan with «Нэмэх», the add pop-up, and a row's edit pop-up, which holds «Устгах»."""
    row = slots.save_row(
        position=macs_writes.save_position("Нягтлан"),
        branch=Branch.objects.create(name="Төв салбар"),
        kind=MAIN,
        year=timezone.localdate().year,
        qty=2,
        by=role_user("hr"),
    )
    return [
        _page(client, reverse("employees:slots"), False),
        _page(client, reverse("employees:slot_add"), True),
        _page(client, reverse("employees:slot_edit", args=[row.pk]), True),
    ]


def _user_change_page(client: Client, role_user: Callable[[str], User]) -> list[str]:
    """A user's admin page: the temporary password button, «Үзэх хүрээ» and the «Идэвхтэй» switch."""
    return [_page(client, reverse("admin:accounts_user_change", args=[role_user("hr").pk]), False)]


def _group_change_page(client: Client, role_user: Callable[[str], User]) -> list[str]:
    """The Admin role group's admin page (its permission cards and «Хадгалах»)."""
    group = Group.objects.get(name="Admin")
    return [_page(client, reverse("admin:auth_group_change", args=[group.pk]), False)]


def _company_change_page(client: Client, role_user: Callable[[str], User]) -> list[str]:
    """The company settings' admin page: the order switches and the slot limit."""
    row = CompanySettings.get()
    return [_page(client, reverse("admin:employees_companysettings_change", args=[row.pk]), False)]


def _order_template_change_page(client: Client, role_user: Callable[[str], User]) -> list[str]:
    """The first order template's admin page, with its file field and «Хадгалах»."""
    OrderTemplate.ensure_all()
    template = OrderTemplate.objects.order_by("pk").first()
    assert template is not None
    return [_page(client, reverse("admin:employees_ordertemplate_change", args=[template.pk]), False)]


def _reference_change_pages(client: Client, role_user: Callable[[str], User]) -> list[str]:
    """A department's and a position's admin pages, each with «Идэвхтэй» and «Хадгалах»."""
    department = macs_writes.save_department("Санхүү")
    position = macs_writes.save_position("Нягтлан")
    return [
        _page(client, reverse("admin:macs_department_change", args=[department.pk]), False),
        _page(client, reverse("admin:macs_position_change", args=[position.pk]), False),
    ]


def _recruitment_change_page(client: Client, role_user: Callable[[str], User]) -> list[str]:
    """The one row of the recruitment settings, on its change page with «Хадгалах»."""
    row = RecruitmentSettings.get()
    return [_page(client, reverse("admin:recruitment_recruitmentsettings_change", args=[row.pk]), False)]


def _leave_row_pages(client: Client, role_user: Callable[[str], User]) -> list[str]:
    """Two recorded leaves of a new hire, one already started and one still ahead: the list shows «Буруу гэж
    тэмдэглэх» and «Цуцлах», and the edit pop-up of one of them shows «Хадгалах»."""
    actor = role_user("hr")
    person = hire_one(actor)
    leave_type = LeaveTypeRow.objects.create(name="Туршилтын чөлөө")
    LeaveTypeExt.objects.create(leave_type=leave_type, uses_annual_balance=False, is_paid=True)
    today = timezone.localdate()
    started = leave_records.record(
        Draft(person, leave_type, today - timedelta(days=14), today - timedelta(days=10)), actor, today
    )
    leave_records.record(
        Draft(person, leave_type, today + timedelta(days=20), today + timedelta(days=24)), actor, today
    )
    return [
        _page(client, reverse("leave:list"), False),  # fetched again: the page the test took first had no rows
        _page(client, reverse("leave:edit", args=[started.pk]), True),
    ]


def _question_pages(client: Client, role_user: Callable[[str], User]) -> list[str]:
    """A question in the assistant's log: the log lists it with the «Засах» link (the corrections right)."""
    HelpQuestion.objects.create(question="Тест асуулт", outcome=Outcome.NONE)
    return [_page(client, reverse("admin:assistant_helpquestion_changelist"), False)]


EXTRA_PAGES: dict[str, ExtraPages] = {
    "employee.hire": _list_page,
    "employee.import": _list_page,
    "today.attention": _attention_today,
    "employee.work_fields": _person_page,
    "employee.note": _person_page,
    "employee.login": _login_popup,
    "employee.setup": _person_page,
    "employee.placement": _change_pages("transfer"),
    "employee.contract": _change_pages("contract"),
    "employee.salary_change": _change_pages("salary_change"),
    "employee.leave_start": _change_pages("leave_start"),
    "employee.leave_return": _change_pages("leave_return", on_long_leave),
    "employee.termination": _change_pages("termination"),
    "employee.rehire": _change_pages("rehire", left),
    "employee.cancel_change": _cancel_pages,
    "employee.correct_job": _correct_job_pages,
    "employee.correct_salary": _correct_salary_pages,
    "employee.first_salary": _first_salary_pages,
    "employee.bank_insurance": _person_page,
    "employee.personal_sections": _person_page,
    "employee.personal_lists": _personal_row_pages,
    "order.edit": _order_popups(False, "employees:order_edit"),
    "order.upload": _order_popups(True, "employees:order_upload"),
    "order.cancel": _order_popups(True, "employees:order_cancel"),
    "order.document": _order_popups(False),
    "recruit.vacancy_add": _vacancy_list_page,
    "recruit.vacancy_edit": _vacancy_pages("recruitment:vacancy_edit"),
    "recruit.vacancy": _vacancy_pages(),
    "recruit.candidate_add": _vacancy_pages("recruitment:candidate_add"),
    "recruit.candidate": _candidate_pages(),
    "recruit.move": _candidate_pages(),
    "recruit.reject": _candidate_pages("recruitment:candidate_reject"),
    "recruit.reopen": _candidate_pages(closed=True),
    "recruit.comment": _candidate_pages(),
    "recruit.file": _candidate_pages(),
    "recruit.convert": _candidate_pages(),
    "recruit.purge": _purge_page,
    "checklist.undo": _open_offboarding_pages,
    "checklist.start": _start_pages,
    "checklist.templates": _template_pages,
    "report.export": _staff_list_page,
    "report.saved_view": _saved_view_pages,
    "list.entry": _list_entry_pages,
    "settings.slot_edit": _slot_pages,
    "settings.users": _user_change_page,
    "settings.roles": _group_change_page,
    "settings.company": _company_change_page,
    "settings.order_templates": _order_template_change_page,
    "settings.departments": _reference_change_pages,
    "settings.recruitment": _recruitment_change_page,
    "settings.assistant": _question_pages,
    "leave.edit": _leave_row_pages,
}


def test_label_match_is_whole_word() -> None:
    assert not on_screen("Ажил", "<a>Ажилтнууд</a>")
    assert on_screen("Ажил", "<a>Ажил</a>")
    assert on_screen("Ажилтан нэмэх", "<a>+ Ажилтан нэмэх</a>")
    assert not on_screen("Хадгалах", "Хадгалахад устгагдана")


def _waiting_detail(role_user: Callable[[str], User]) -> tuple[User, str]:
    """A line manager (approver) with one waiting request from a report. Returns the manager and the detail URL."""
    boss = role_user("approver")
    own = EmployeeExt.objects.get(user=boss).employee
    report = JobRecord.objects.filter(manager=own).first().employee  # type: ignore[union-attr]
    creator = User.objects.create_superuser("help_creator", password=PASSWORD)  # a line manager may not be the creator
    leave_type = LeaveTypeRow.objects.create(name="Туршилтын амралт")
    LeaveTypeExt.objects.create(leave_type=leave_type, uses_annual_balance=False, is_paid=True)
    req = request_service.submit(report, leave_type, date(2026, 11, 10), date(2026, 11, 11), "", creator, TODAY)
    return boss, reverse("leave:request_detail", args=[req.pk])


@pytest.mark.parametrize(("key", "role"), PAIRS)
def test_every_entry_opens_for_its_user(role_user: Callable[[str], User], key: str, role: str) -> None:
    _skip_unless_offered(key, role)
    entry = ENTRY_BY_KEY[key]
    kind, approval = ROLE_SETUP[role]
    _set_approval(approval)
    client = _client(role_user(kind))
    _page(client, entry.url(), entry.modal)


@pytest.mark.parametrize(("key", "role"), PAIRS)
def test_every_label_is_on_screen(role_user: Callable[[str], User], key: str, role: str) -> None:
    _skip_unless_offered(key, role)
    entry = ENTRY_BY_KEY[key]
    kind, approval = ROLE_SETUP[role]
    _set_approval(approval)
    client = _client(role_user(kind))
    bodies = [_page(client, entry.url(), entry.modal)]
    is_leave = key.startswith("leave.")
    if key == "leave.request":
        bodies.append(_page(client, reverse("me"), False))
    elif is_leave and key != "leave.decide":  # the requests page is the entry itself (approvers: no leave:list)
        bodies.append(_page(client, reverse("leave:list"), False))
    if key == "leave.decide":
        # Батлах / Татгалзах are on the request detail page, seen by the line manager of a waiting request.
        boss, detail_url = _waiting_detail(role_user)
        bodies.append(_page(_client(boss), detail_url, False))
    extra = EXTRA_PAGES.get(key)
    if extra is not None:
        bodies.extend(extra(client, role_user))
    missing = [label for label in entry.labels if not any(on_screen(label, body) for body in bodies)]
    assert not missing, f"{key} as {role}: not on screen: {missing}"


ADMIN_ONLY_KEYS = (
    "settings.users",
    "settings.roles",
    "settings.company",
    "settings.order_templates",
    "settings.departments",
)


@pytest.mark.parametrize("key", ADMIN_ONLY_KEYS)
def test_admin_only_entry_for_a_superuser(key: str) -> None:
    """No role of the test set holds these admin rights by default, so the entry is checked as a superuser (who holds
    every right): it is offered, and its labels are on the admin page and its pop-ups."""
    root = User.objects.create_superuser("help_root", password=PASSWORD)
    entry = ENTRY_BY_KEY[key]
    client = _client(root)
    bodies = [_page(client, entry.url(), entry.modal)]
    bodies.extend(EXTRA_PAGES[key](client, lambda kind: root))
    assert key in [e.key for e in allowed_entries(root, TODAY)]
    missing = [label for label in entry.labels if not any(on_screen(label, body) for body in bodies)]
    assert not missing, f"{key} as a superuser: not on screen: {missing}"


def test_slot_override_only_when_limit_is_on(role_user: Callable[[str], User]) -> None:
    """The slot-limit entry is offered only while «Орон тоогоор хязгаарлах» is switched on, and its labels are on the
    position-slot plan then."""
    user = role_user("hr")
    entry = ENTRY_BY_KEY["settings.slot_override"]
    assert entry.key not in [e.key for e in allowed_entries(user, TODAY)]
    CompanySettings.objects.update_or_create(pk=1, defaults={"enforce_position_slots": True})
    assert entry.key in [e.key for e in allowed_entries(user, TODAY)]
    body = _page(_client(user), entry.url(), False)
    missing = [label for label in entry.labels if not on_screen(label, body)]
    assert not missing, f"settings.slot_override as hr: not on screen: {missing}"


@pytest.mark.parametrize(
    ("key", "perm", "offered"),
    [
        ("settings.assistant", "assistant.view_helpexample", False),
        ("settings.assistant", "assistant.view_helpquestion", True),
        ("settings.departments", "macs.view_position", False),
        ("settings.departments", "macs.view_department", True),
    ],
)
def test_admin_entry_needs_the_right_of_its_page(
    role_user: Callable[[str], User], key: str, perm: str, offered: bool
) -> None:
    """A staff user is offered an admin entry only with the right of the page the entry opens, not with a right on
    another page the entry mentions; the page answers 200 exactly when the entry is offered."""
    user = role_user("none")
    user.is_staff = True
    user.save(update_fields=["is_staff"])
    app_label, codename = perm.split(".")
    user.user_permissions.add(Permission.objects.get(codename=codename, content_type__app_label=app_label))
    user = User.objects.get(pk=user.pk)  # a fresh instance, so the permission cache is empty
    entry = ENTRY_BY_KEY[key]
    assert (key in [e.key for e in allowed_entries(user, TODAY)]) is offered
    status = _client(user).get(entry.url()).status_code
    assert (status == 200) is offered, f"{key} with {perm}: page answered {status}"


def test_hr_gets_no_admin_settings_entry(role_user: Callable[[str], User]) -> None:
    """HR holds no admin rights: of the settings entries only the position-slot plan is offered to HR."""
    keys = [e.key for e in allowed_entries(role_user("hr"), TODAY) if e.key.startswith("settings.")]
    assert keys == ["settings.slots", "settings.slot_edit"]
