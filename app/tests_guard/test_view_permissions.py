"""Every view declares who may open it (OQ-079).

Spec: docs/superpowers/specs/2026-10-29-data-scope-and-team-design.md, section 6.

A new screen cannot ship open by accident: every named URL must have an entry in EXPECTED, and every entry is
probed against the real routes:

1. the registry and the routes list the same names (new or stale names fail), and every URL pattern has a name
   (UNNAMED_ALLOWED lists the only exceptions);
2. an anonymous visitor is sent to the login page (or gets 405 for a wrong method);
3. a logged-in user who SEES the employee (macs.view_employees, so the employee-pk routes reach their gate) but holds
   no other right is refused on every permission route whose rule needs more, and the request changes no row. A user
   with no right at all is refused on the one rule that is only `macs.view_employees` (the system log);
4. a user holding exactly the codenames of the rule, plus macs.view_employees, gets past the permission gate (not 403,
   not a login redirect, not 404). Every probe runs in a savepoint that is rolled back, so one request cannot change
   the objects the next one needs;
5. every report key: the page, print and Excel are refused without the report's `needs` and open with them.

Routes that look up a sub-object BEFORE the gate (order, event, salary or job row, saved view) get a real object from
`scenario`. A route whose sub-object is not built here is listed in NOT_PROVEN with the reason: its refusal may then be
a 404, and it gets no positive probe.

The rules come from docs/phase1/permission-matrix.md, checked against the view code (the code wins).
Skipped: the Django admin (`/admin/`, namespace "admin") has its own model permissions and is not listed here.
"""

from __future__ import annotations

import enum
import hashlib
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from accounts.models import User
from django.apps import apps
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.test import Client
from django.urls import URLPattern, URLResolver, get_resolver, reverse
from django.utils import timezone
from employees.models import Employee, HrOrder
from employees.services import events, history, macs_writes, orders
from employees.tests.conftest import hire_values
from reports.models import SavedView
from reports.registry import REPORTS


class Open(enum.Enum):
    """Rules that are not a permission gate."""

    LOGIN_ONLY = "login only"
    PUBLIC = "public"


LOGIN_ONLY = Open.LOGIN_ONLY
PUBLIC = Open.PUBLIC


@dataclass(frozen=True)
class AnyOf:
    """Passes when the user holds at least one of the codenames (the view checks them one by one)."""

    codenames: tuple[str, ...]


@dataclass(frozen=True)
class Conditional:
    """Login, then a right that depends on the object (OQ-080). A signed scan of a hire or rehire order (it shows the
    salary) needs `object_right`; any other order needs only a visible employee, which the view checks first (404).
    The probes use the signed hire order of a visible employee, so the refusal is a 403, not a 404 for a missing order.
    """

    object_right: str


# A permission rule is a tuple of codenames that must ALL be held, AnyOf(...) for "one of them is enough", or
# Conditional(...) for a right that depends on the object.
Rule = Open | tuple[str, ...] | AnyOf | Conditional

VIEW_ONLY: tuple[str, ...] = ("macs.view_employees",)

# Every named URL of the project. Keys are full names (namespace:name). The value says what the view needs.
EXPECTED: dict[str, Rule] = {
    # --- config/urls.py ---
    "home": LOGIN_ONLY,  # only redirects by role (Auditor to the system log, others to Today); shows no HR data
    "me": LOGIN_ONLY,  # My page: the user's own employee record only (404 without one); no other person's data
    "me_notice": LOGIN_ONLY,  # POST; dismisses one of the user's own leave-result notices only
    # POST; 400 without a question, 404 when the assistant is off; answers only from the user's allowed entries
    "assistant:ask": LOGIN_ONLY,
    "login": PUBLIC,  # the login form itself
    "logout": PUBLIC,  # ends the session
    "password_change": LOGIN_ONLY,  # changes the user's own password only
    "set_language": PUBLIC,  # Django language switch; no HR data
    # --- employees (employees/urls.py) ---
    "employees:today": LOGIN_ONLY,  # Today page: rows come from visible_employees (own record only for Employee)
    "employees:today_away": LOGIN_ONLY,  # fragment: rows from visible_employees; names need the leave right
    "employees:today_upcoming": LOGIN_ONLY,  # fragment: rows from visible_employees; birthdays need the personal right
    "employees:list": LOGIN_ONLY,  # rows from visible_employees; register no. only with view_personal
    "employees:orders": LOGIN_ONLY,  # order register rows come from visible_employees (order_register.py:85)
    "employees:orders_print": LOGIN_ONLY,  # same rows as the register
    "employees:order_suggest": ("macs.manage_employees",),
    "employees:add": ("macs.manage_employees",),
    "employees:attention": LOGIN_ONLY,  # POST; attention.items(user) filters by the user's own rights
    "employees:attention_more": LOGIN_ONLY,  # items from visible employees only
    "employees:check_register": ("macs.manage_employees",),
    "employees:district_options": ("macs.manage_employees",),
    "employees:palette": LOGIN_ONLY,  # each result kind is checked on its own (palette.py)
    "employees:import": ("macs.manage_employees",),
    "employees:import_template": ("macs.manage_employees",),
    "employees:import_map": ("macs.manage_employees",),
    "employees:import_preview": ("macs.manage_employees",),
    "employees:import_run": ("macs.manage_employees",),
    "employees:import_result": ("macs.manage_employees",),
    "employees:import_rejected": ("macs.manage_employees",),
    "employees:detail": LOGIN_ONLY,  # _employee_for = visible_employees; each tab is gated inside the view
    "employees:save": AnyOf(("macs.manage_employees", "macs.manage_salary")),  # each form only for its own right
    "employees:login_create": ("macs.manage_employees",),
    "employees:setup_toggle": ("macs.manage_employees",),
    "employees:personal_section": ("macs.manage_employees", "macs.view_personal"),  # _personal_access
    "employees:note": ("macs.manage_employees",),
    "employees:activity_more": LOGIN_ONLY,  # activity filtered by visible_activity
    "employees:correct_job": ("macs.manage_employees",),
    "employees:correct_salary": ("macs.manage_salary", "macs.view_salary"),  # can_manage_salary needs both
    "employees:set_salary": ("macs.manage_salary", "macs.view_salary"),  # can_manage_salary needs both
    "employees:event": AnyOf(("macs.manage_employees", "macs.manage_salary")),  # type decides (can_record_event)
    "employees:event_cancel": AnyOf(("macs.manage_employees", "macs.manage_salary")),  # can_cancel decides
    "employees:order_edit": ("macs.manage_employees",),
    "employees:order_upload": ("macs.manage_employees",),
    "employees:order_detail": LOGIN_ONLY,  # _order_for = visible employee; edit and cancel buttons gated
    "employees:order_cancel": ("macs.manage_employees",),
    "employees:order_history": LOGIN_ONLY,  # _order_for = visible employee (audit note N2)
    # OQ-080: the signed scan of a hire or rehire order shows the salary, so it needs macs.view_salary; other orders
    # need only a visible employee (access.can_open_order_scan, checked after _order_for).
    "employees:order_file": Conditional(object_right="macs.view_salary"),
    "employees:order_document": ("macs.manage_employees",),
    "employees:order_document_pdf": ("macs.manage_employees",),
    "employees:orders_print_selected": ("macs.manage_employees",),
    "employees:personal_list": ("macs.manage_employees", "macs.view_personal"),
    "employees:personal_add": ("macs.manage_employees", "macs.view_personal"),
    "employees:personal_edit": ("macs.manage_employees", "macs.view_personal"),
    "employees:personal_delete": ("macs.manage_employees", "macs.view_personal"),
    "employees:slots": ("employees.manage_position_slots",),
    "employees:slot_add": ("employees.manage_position_slots",),
    "employees:slot_edit": ("employees.manage_position_slots",),
    "employees:slot_delete": ("employees.manage_position_slots",),
    # --- leave (leave/urls.py); record = record_leave AND view_leave (leave/access.py) ---
    # Requests (spec 5.6, 5.7): the gate is per request or per own record, checked in the view, not a plain right.
    "leave:requests": LOGIN_ONLY,  # the user's own queue; the «Бүгд» tab is 403 without view_leave (in the view)
    "leave:request_detail": LOGIN_ONLY,  # 404 unless the user may act on the request or may view the person's leave
    "leave:request_approve": LOGIN_ONLY,  # POST; 404 unless the user may act on that request (_visible_request)
    "leave:request_reject": LOGIN_ONLY,  # POST; 404 unless the user may act on that request (_visible_request)
    "leave:request_new": LOGIN_ONLY,  # POST/GET; 403 unless request_own_leave, an own employee record, approval on
    "leave:request_check": LOGIN_ONLY,  # POST only; same refusal as request_new (the own record only)
    "leave:request_withdraw": LOGIN_ONLY,  # POST; the own employee's request only (404 for anyone else's)
    "leave:list": ("leave.view_leave",),
    "leave:add": ("leave.record_leave", "leave.view_leave"),
    "leave:check": ("leave.record_leave", "leave.view_leave"),
    "leave:edit": ("leave.record_leave", "leave.view_leave"),
    "leave:cancel": ("leave.record_leave", "leave.view_leave"),
    "leave:grant": ("leave.record_leave", "leave.view_leave"),
    "leave:grant_bulk": ("leave.record_leave", "leave.view_leave"),
    "leave:adjust": ("leave.record_leave", "leave.view_leave"),
    "leave:carry": ("leave.record_leave", "leave.view_leave"),
    "leave:calendar": ("leave.view_leave",),
    "leave:balances": ("leave.view_leave",),
    "leave:holidays": ("leave.manage_leave_settings",),
    "leave:settings": ("leave.manage_leave_settings",),
    "leave:type_add": ("leave.manage_leave_settings",),
    "leave:type_edit": ("leave.manage_leave_settings",),
    "leave:type_delete": ("leave.manage_leave_settings",),
    # --- checklists (checklists/urls.py): POST only; the gate is per task or per employee, checked in the view, and
    # every refusal is a 404 so the answer never says a task exists (offboarding-checklist spec) ---
    "checklists:tick": LOGIN_ONLY,  # POST; 404 unless the user is an owner of that open task (owners.can_tick)
    "checklists:untick": LOGIN_ONLY,  # POST; 404 unless manage_employees and the employee is visible (data scope)
    "checklists:start": LOGIN_ONLY,  # POST; 404 unless the employee is visible and the user may record a termination
    "checklists:cancel": LOGIN_ONLY,  # POST; 404 unless manage_employees and the checklist is visible (data scope)
    "checklists:mine": LOGIN_ONLY,  # GET; the user's own open tasks, empty for a non-owner
    # --- recruitment (recruitment/urls.py): objects come from recruitment.services.visibility (404 for what the user
    # may not see); a visible object's manage-only action is 403 for a hiring manager (access.require_manage) ---
    "recruitment:vacancies": LOGIN_ONLY,  # rows come from visible_vacancies (hiring managers: their own vacancies only)
    "recruitment:vacancy_add": ("recruitment.manage_recruitment",),
    "recruitment:vacancy_slot_line": ("recruitment.manage_recruitment",),  # the pop-up's budget line (advisory)
    "recruitment:vacancy_detail": LOGIN_ONLY,  # 404 unless the vacancy is visible
    "recruitment:vacancy_edit": LOGIN_ONLY,  # 404 unless visible, then 403 without manage_recruitment
    "recruitment:candidate_add": LOGIN_ONLY,  # 404 unless the vacancy is visible, then 403 without manage_recruitment
    "recruitment:candidate_detail": LOGIN_ONLY,  # 404 unless the candidate is visible (visible_candidates)
    "recruitment:candidate_convert": LOGIN_ONLY,  # 404 unless visible, then 403 without manage_recruitment; GET only
    "recruitment:purge": ("recruitment.manage_recruitment",),
    "recruitment:candidate_move": LOGIN_ONLY,  # POST; 404 unless visible, then 403 without manage_recruitment
    "recruitment:candidate_reject": LOGIN_ONLY,  # 404 unless visible, then 403 without manage_recruitment
    "recruitment:candidate_reopen": LOGIN_ONLY,  # POST; 404 unless visible, then 403 without manage_recruitment
    "recruitment:candidate_comment": LOGIN_ONLY,  # POST; 404 unless visible; hiring managers may comment
    "recruitment:candidate_file_upload": LOGIN_ONLY,  # POST; 404 unless visible, then 403 without manage_recruitment
    "recruitment:candidate_file": LOGIN_ONLY,  # private CV download; 404 unless the candidate is visible
    # --- reports (reports/urls.py); each report's own `needs` are checked by registry.can_open, see test 5 ---
    "reports:catalogue": ("reports.view_reports",),
    "reports:report": ("reports.view_reports",),
    "reports:columns": ("reports.view_reports",),
    "reports:print": ("reports.view_reports",),
    "reports:excel": ("reports.view_reports", "accounts.export_lists"),
    "reports:view_new": ("reports.view_reports",),
    "reports:view_edit": ("reports.view_reports",),  # plus author or reports.manage_saved_views (object check)
    "reports:view_delete": ("reports.view_reports",),  # same object check as view_edit
    # --- lists (lists/urls.py): every view has @permission_required ---
    "lists:index": ("lists.manage_lists",),
    "lists:meaning": ("lists.manage_lists",),
    "lists:list": ("lists.manage_lists",),
    "lists:add": ("lists.manage_lists",),
    "lists:quick_add": ("lists.manage_lists",),
    "lists:edit": ("lists.manage_lists",),
    "lists:delete": ("lists.manage_lists",),
    # --- logs (logs/urls.py) ---
    "logs:employee": ("macs.view_employees",),
    "logs:system": ("accounts.view_audit",),
    "logs:employee_xlsx": ("macs.view_employees", "accounts.export_lists"),
    "logs:system_xlsx": ("accounts.view_audit", "accounts.export_lists"),
}

# Names not probed, with the reason. Every PUBLIC entry must be here (checked in test 2).
SKIP: dict[str, str] = {
    "login": "public by design: the login form itself",
    "logout": "public by design: ends the session; anonymous logout does nothing",
    "set_language": "public by design: Django language switch, no HR data",
}

# Permission routes whose sub-object this file does not build, so the refusal may be a 404 (the object is missing
# before the gate, or the gate is only reached with an object). They get no positive probe (test 4). The set is
# asserted by test_not_proven_set_is_exact; growing it needs a deliberate edit there.
NOT_PROVEN: dict[str, str] = {
    "employees:personal_edit": "needs a saved personal row of kind family (its key); not built here",
    "employees:personal_delete": "needs a saved personal row of kind family (its key); not built here",
    "employees:import_map": "needs a staff Excel draft (StaffImportDraft with a file); not built here",
    "employees:import_preview": "needs a staff Excel draft (StaffImportDraft with a file); not built here",
    "employees:import_run": "needs a staff Excel draft (StaffImportDraft with a file); not built here",
    "employees:import_result": "needs a staff Excel draft (StaffImportDraft with a file); not built here",
    "employees:import_rejected": "needs a staff Excel draft (StaffImportDraft with a file); not built here",
    "leave:edit": "needs a leave request of the probe user (_own_leave); not built here",
    "leave:cancel": "needs a leave request of the probe user (_own_leave); not built here",
    "leave:type_edit": "needs a leave type row (LeaveTypeRow); not built here",
    "leave:type_delete": "needs a leave type row (LeaveTypeRow); not built here",
    "employees:slot_edit": "needs a position-slot row (nazg, by pk); not built here",
    "employees:slot_delete": "needs a position-slot row (nazg, by pk); not built here",
    "lists:edit": "needs a list entry of a lookup list (pk); not built here",
    "lists:delete": "needs a list entry of a lookup list (pk); not built here",
}

SKIPPED_NAMESPACES = frozenset({"admin"})  # Django admin: its own model permissions, not this registry

# Unnamed URL patterns that may exist, keyed by the view's dotted path, with the reason. Anything else unnamed fails.
UNNAMED_ALLOWED: dict[str, str] = {
    "django.views.static.serve": (
        "DEBUG-only media route from config/urls.py static(settings.MEDIA_URL); static() returns nothing when DEBUG "
        "is off, so it is normally absent in tests"
    ),
}

# Refusals accepted for a user without the right: 403 (the gate) and 405 (the wrong method is refused before the gate;
# the other method is probed too), or a redirect to the login page (permission_required sends a logged-in user there).
ALLOWED_REFUSAL = {403, 405}

# Statuses that count as "got past the gate" for a user who holds the rule: 200, 204, 400 (a form or key the view
# refuses after the gate), 405 (the other method), or a redirect that is not to the login page (see _passed).
PASSED = {200, 204, 400, 405}

# Apps whose tables are compared before and after a refused request.
GUARDED_APPS = frozenset({"auth", "accounts", "macs", "employees", "leave", "lists", "reports", "logs"})

# Sample values for path arguments that are not an object of the scenario.
UNKNOWN_UUID = uuid.UUID(int=1)
SAMPLE_VALUES: dict[str, str] = {
    "slug": "marital_status",  # a lookup list (lists/registry.py)
    "key": "staff-list",  # a report (reports/staff_list.py)
    "kind": "family",  # a personal list (employees/views.py FORMS)
    "section": "identity",  # a personal tab section (employees/sections.py)
    "type": "transfer",  # an event type (employees/models.py EventType)
    "start": "2026-01-01",
    "end": "2026-12-31",
}
ARG_OVERRIDES: dict[str, dict[str, Any]] = {
    # `key` is not a setup item. The gate passes for the new hire (its setup is still required), then the view
    # answers 400 for the unknown item.
    "employees:setup_toggle": {"key": "x"},
    # The simple lists have no quick-add pop-up (GET is 404 for them, after the gate); country has an extra field, so
    # its pop-up opens.
    "lists:quick_add": {"slug": "country"},
}
LEAVE_EMPLOYEE_ROUTES = frozenset({"leave:grant", "leave:adjust", "leave:carry"})  # pk is an employee there too
VIEW_ROUTES = frozenset({"reports:view_edit", "reports:view_delete"})  # pk is a saved report view there

_CONVERTER = re.compile(r"<(?:(?P<conv>\w+):)?(?P<name>\w+)>")
SCAN = b"%PDF-1.4\n%test\n"


@dataclass(frozen=True)
class Subject:
    """An employee and the pk of its hire order (the probes use a real one for the order routes)."""

    employee: Employee
    order: int


@dataclass(frozen=True)
class Scenario:
    """The real objects the probes address. Each one has the state its route needs (see the field comments)."""

    actor: User
    pending: Subject  # hire order PENDING: nothing registered (order_edit, order_detail, ...)
    registered: Subject  # hire order REGISTERED: a number, no scan (order_cancel)
    signed: Subject  # hire order SIGNED with a scan (order_file)
    no_salary: Subject  # a hire with no salary row (set_salary)
    event: int  # a future contract change of `pending`, scheduled (event_cancel)
    job_record: int  # `pending`'s hire job row (correct_job)
    salary_record: int  # `pending`'s hire salary row (correct_salary)
    view: int  # a saved report view written by `actor` (view_edit, view_delete)


def _walk(patterns: list[Any], prefix: str, namespace: str) -> list[tuple[str | None, str, str]]:
    """Every URL pattern as (full name or None, route, dotted path of its view), namespaces included; the admin
    namespace is skipped."""
    found: list[tuple[str | None, str, str]] = []
    for p in patterns:
        route = prefix + str(p.pattern)
        if isinstance(p, URLResolver):
            if p.namespace in SKIPPED_NAMESPACES:
                continue
            child = f"{namespace}{p.namespace}:" if p.namespace else namespace
            found.extend(_walk(p.url_patterns, route, child))
        elif isinstance(p, URLPattern):
            callback = p.callback
            dotted = f"{callback.__module__}.{callback.__qualname__}"
            found.append((f"{namespace}{p.name}" if p.name else None, route, dotted))
    return found


def _all_patterns() -> list[tuple[str | None, str, str]]:
    return _walk(get_resolver().url_patterns, "", "")


def _named_routes() -> dict[str, str]:
    """Full name -> route for every named URL, namespaced like `employees:detail`."""
    return {name: route for name, route, _ in _all_patterns() if name is not None}


def _is_permission(rule: Rule) -> bool:
    return not isinstance(rule, Open)


def _url(name: str, route: str, ids: dict[str, int]) -> str:
    """The URL for a route. `ids` gives the real object for an argument; other arguments get a sample value."""
    kwargs: dict[str, Any] = {}
    for match in _CONVERTER.finditer(route):
        conv, arg = match["conv"], match["name"]
        if conv == "uuid":
            value: Any = UNKNOWN_UUID
        elif arg in ids:
            value = ids[arg]
        elif arg in ARG_OVERRIDES.get(name, {}):
            value = ARG_OVERRIDES[name][arg]
        elif conv in ("int", "sint"):
            value = 1
        else:
            value = SAMPLE_VALUES.get(arg, "x")
        kwargs[arg] = value
    return reverse(name, kwargs=kwargs)


def _ids(name: str, s: Scenario, view_pk: int = 0) -> dict[str, int]:
    """The real object ids for one route (empty for routes that take no object)."""
    if name in LEAVE_EMPLOYEE_ROUTES:
        return {"pk": s.pending.employee.pk}
    if name in VIEW_ROUTES:
        return {"pk": view_pk}
    if not name.startswith("employees:"):
        return {}
    subject = {
        "employees:order_file": s.signed,
        "employees:order_cancel": s.registered,
        "employees:set_salary": s.no_salary,
    }.get(name, s.pending)
    ids = {"pk": subject.employee.pk, "order_id": subject.order, "event_id": s.event}
    if name == "employees:correct_job":
        ids["record_id"] = s.job_record
    if name == "employees:correct_salary":
        ids["record_id"] = s.salary_record
    return ids


def _granted(name: str, rule: Rule) -> tuple[str, ...]:
    """The codenames the positive control grants: all of a tuple, the first of an AnyOf, plus a report's needs.
    A Conditional grants the visibility right and its object right."""
    if isinstance(rule, Conditional):
        return (*VIEW_ONLY, rule.object_right)
    codenames = rule.codenames[:1] if isinstance(rule, AnyOf) else tuple(rule)  # type: ignore[arg-type]
    if name.startswith("reports:"):
        codenames += REPORTS[SAMPLE_VALUES["key"]].needs
    return codenames


def _grant(user: User, codenames: tuple[str, ...]) -> None:
    for full in codenames:
        app_label, codename = full.split(".")
        user.user_permissions.add(Permission.objects.get(content_type__app_label=app_label, codename=codename))


def _client_for(username: str, codenames: tuple[str, ...]) -> tuple[Client, User]:
    """A signed-in client with exactly these codenames. The first request of the day runs the daily MACS sync
    (employees/daily_sync.py), a write that is not the view's, so it is done here, before any snapshot."""
    user = User.objects.create_user(username, password="x-long-pass-123")  # noqa: S106
    user.groups.clear()  # new users get the Employee group automatically (accounts/signals.py)
    _grant(user, codenames)
    client = Client()
    client.force_login(user)
    client.get(reverse("home"))
    return client, user


def _db_state() -> str:
    """A digest of every row of the guarded apps: any insert, update or delete changes it."""
    digest = hashlib.sha256()
    for model in apps.get_models():
        if model._meta.app_label not in GUARDED_APPS:
            continue
        fields = [f.attname for f in model._meta.concrete_fields]
        for row in model._base_manager.order_by("pk").values_list(*fields):
            digest.update(repr((model._meta.label, row)).encode())
    return digest.hexdigest()


def _login_redirect(response: Any) -> bool:
    return response.status_code == 302 and "/login/" in response["Location"]


def _refused(name: str, response: Any) -> bool:
    """A user without the right gets 403 (or 405), or a redirect to the login page. 404 counts only for NOT_PROVEN."""
    if response.status_code in ALLOWED_REFUSAL or _login_redirect(response):
        return True
    return name in NOT_PROVEN and response.status_code == 404


def _passed(response: Any) -> bool:
    """A user with the right got past the gate: not a 403, not a 404, not a login redirect."""
    if _login_redirect(response):
        return False
    if 300 <= response.status_code < 400:  # a redirect that is not to the login page (a save goes to its page)
        return True
    return response.status_code in PASSED


def _probe(send: Callable[[str], Any], url: str) -> Any:
    """One request in a savepoint that is rolled back, so a POST that writes does not change the next probe."""
    with transaction.atomic():
        response = send(url)
        transaction.set_rollback(True)
    return response


def _first_pk(qs: Any) -> int:
    row = qs.order_by("pk").first()
    assert row is not None  # noqa: S101
    return int(row.pk)


def _hire(actor: User, number: int, salary: Decimal | None, job: dict[str, Any]) -> Subject:
    employee = history.hire(
        hire_values(f"УБ9912000{number}"), {}, start=date(2026, 1, 5), job=job, salary=salary, by=actor
    )
    return Subject(employee, HrOrder.objects.get(employee=employee, is_hire=True).pk)


@pytest.fixture
def scenario(db: None) -> Scenario:
    actor = User.objects.create_user("guard_actor", password="x-long-pass-123")  # noqa: S106
    job = {
        "position": macs_writes.save_position("Нягтлан"),
        "department": macs_writes.save_department("Санхүү"),
        "employee_type": "full_time",
        "status": "active",
        "contract_type": "open_ended",
    }
    pending = _hire(actor, 1, Decimal("2500000"), job)
    registered = _hire(actor, 2, Decimal("2500000"), job)
    orders.register(
        HrOrder.objects.get(pk=registered.order), number="16", date=date(2026, 1, 5), summary="", issued_by="", by=actor
    )
    signed = _hire(actor, 3, Decimal("2500000"), job)
    signed_order = HrOrder.objects.get(pk=signed.order)
    orders.register(signed_order, number="15", date=date(2026, 1, 5), summary="", issued_by="", by=actor)
    signed_order.refresh_from_db()
    orders.attach_signed_file(signed_order, SimpleUploadedFile("scan.pdf", SCAN, "application/pdf"), by=actor)
    no_salary = _hire(actor, 4, None, job)
    event = events.record(
        pending.employee,
        type="contract",
        effective=timezone.localdate() + timedelta(days=30),
        changes={"contract_no": "CN-GUARD"},
        salary=None,
        reason="",
        note="",
        by=actor,
    )
    view = SavedView.objects.create(report="staff-list", name="guard view", author=actor)
    return Scenario(
        actor=actor,
        pending=pending,
        registered=registered,
        signed=signed,
        no_salary=no_salary,
        event=event.pk,
        job_record=_first_pk(pending.employee.job_records.all()),
        salary_record=_first_pk(pending.employee.salary_records.all()),
        view=view.pk,
    )


def test_every_url_name_is_registered() -> None:
    callbacks = {name: dotted for name, _, dotted in _all_patterns() if name is not None}
    routed = set(callbacks)
    registered = set(EXPECTED)
    new = sorted(routed - registered)
    stale = sorted(registered - routed)
    assert not new, (
        "URL name(s) with no entry: "
        + "; ".join(f"{n} (view {callbacks[n]})" for n in new)
        + ". Add the new URL name to EXPECTED in app/tests_guard/test_view_permissions.py with the permission its "
        "view requires (or LOGIN_ONLY with a reason)."
    )
    assert not stale, (
        f"EXPECTED lists URL name(s) that are no longer routed: {stale}. "
        "Remove them from EXPECTED in app/tests_guard/test_view_permissions.py (or restore the route)."
    )


def test_every_url_pattern_is_named_or_allowed() -> None:
    offenders = [
        f"{route} (view {dotted})"
        for name, route, dotted in _all_patterns()
        if name is None and dotted not in UNNAMED_ALLOWED
    ]
    assert not offenders, (
        "Unnamed URL pattern(s): "
        + "; ".join(offenders)
        + ". Give each route a name= so the guard can probe it, or, if it is a framework route that is not a screen, "
        "add its view's dotted path to UNNAMED_ALLOWED in app/tests_guard/test_view_permissions.py with the reason."
    )


def test_public_entries_are_skipped_on_purpose() -> None:
    public = sorted(name for name, rule in EXPECTED.items() if rule is PUBLIC)
    assert public == sorted(SKIP), "Every PUBLIC entry must be listed in SKIP with its reason, and only those."


def test_not_proven_set_is_exact() -> None:
    """Prints the routes whose gate is not proven by a positive probe, and fails if the set changes unnoticed."""
    print(f"\nNOT_PROVEN ({len(NOT_PROVEN)}): " + ", ".join(sorted(NOT_PROVEN)))
    assert sorted(NOT_PROVEN) == sorted(
        [
            "employees:import_map",
            "employees:import_preview",
            "employees:import_result",
            "employees:import_rejected",
            "employees:import_run",
            "employees:personal_delete",
            "employees:personal_edit",
            "employees:slot_delete",
            "employees:slot_edit",
            "lists:delete",
            "lists:edit",
            "leave:cancel",
            "leave:edit",
            "leave:type_delete",
            "leave:type_edit",
        ]
    )
    assert all(_is_permission(EXPECTED[name]) for name in NOT_PROVEN)


def test_anonymous_is_sent_to_login(scenario: Scenario) -> None:
    offenders: list[str] = []
    routes = _named_routes()
    for name in EXPECTED:
        if name in SKIP:
            continue
        url = _url(name, routes[name], _ids(name, scenario, scenario.view))
        for method in ("get", "post"):
            response = getattr(Client(), method)(url)
            if response.status_code == 405 or _login_redirect(response):
                continue
            offenders.append(f"{name} {method.upper()} {url} -> {response.status_code} (expected 302 to /login/)")
    assert not offenders, "Anonymous visitors reached these views:\n" + "\n".join(offenders)


def test_user_without_permissions_is_refused(scenario: Scenario) -> None:
    """A user who sees the employee but holds nothing else is refused on every permission route (403, or the login
    redirect of permission_required); a user with no right at all is refused on the system-log style rule. No row
    changes in any refused request."""
    plain, _ = _client_for("guard_no_rights", ())
    viewer, _ = _client_for("guard_viewer", VIEW_ONLY)
    routes = _named_routes()
    offenders: list[str] = []
    for name, rule in EXPECTED.items():
        if not _is_permission(rule):
            continue
        client = plain if rule == VIEW_ONLY else viewer
        url = _url(name, routes[name], _ids(name, scenario, scenario.view))
        for method in ("get", "post"):
            before = _db_state()
            response = getattr(client, method)(url)
            if not _refused(name, response):
                offenders.append(f"{name} {method.upper()} -> {response.status_code} (expected 403, 405 or login)")
            if _db_state() != before:
                offenders.append(f"{name} {method.upper()} changed the database")
    assert not offenders, "A user without the right got through:\n" + "\n".join(offenders)


def test_conditional_entries_refuse_a_visible_employee_without_the_object_right(scenario: Scenario) -> None:
    """A Conditional entry answers 403 (not 404) to a user who sees the employee but lacks the object right."""
    viewer, _ = _client_for("guard_visible_only", VIEW_ONLY)
    routes = _named_routes()
    offenders: list[str] = []
    for name, rule in EXPECTED.items():
        if not isinstance(rule, Conditional):
            continue
        url = _url(name, routes[name], _ids(name, scenario, scenario.view))
        for method in ("get", "post"):
            before = _db_state()
            response = getattr(viewer, method)(url)
            if response.status_code != 403:
                offenders.append(
                    f"{name} {method.upper()} -> {response.status_code} (expected 403, needs {rule.object_right})"
                )
            if _db_state() != before:
                offenders.append(f"{name} {method.upper()} changed the database")
    assert not offenders, "A visible employee without the object right got through:\n" + "\n".join(offenders)


def test_user_with_the_permission_passes_the_gate(scenario: Scenario) -> None:
    """Each rule's codenames, plus macs.view_employees so the employee is visible, pass the gate. A probe that is
    refused, or answered 404 for a missing object, fails. NOT_PROVEN routes are not probed here."""
    routes = _named_routes()
    offenders: list[str] = []
    for name, rule in EXPECTED.items():
        if not _is_permission(rule) or name in NOT_PROVEN:
            continue
        codenames = tuple(dict.fromkeys((*_granted(name, rule), *VIEW_ONLY)))
        client, user = _client_for(f"guard_{name.replace(':', '_')}", codenames)
        own_view = SavedView.objects.create(report="staff-list", name=user.username, author=user).pk
        url = _url(name, routes[name], _ids(name, scenario, own_view))
        for method in ("get", "post"):
            response = _probe(getattr(client, method), url)
            if not _passed(response):
                offenders.append(f"{name} {method.upper()} -> {response.status_code} with {list(codenames)}")
    assert not offenders, "A user with the required permission was refused or hit a missing object:\n" + "\n".join(
        offenders
    )


@pytest.mark.parametrize("key", sorted(REPORTS))
def test_report_needs_are_enforced(key: str, db: None) -> None:
    """A report's own `needs` (registry.can_open): without them the page, print and Excel are refused with 403; with
    them they open (200). The base user holds view_reports, view_employees and export_lists."""
    report = REPORTS[key]
    base = ("reports.view_reports", *VIEW_ONLY, "accounts.export_lists")
    without, _ = _client_for(f"guard_rep_{key}_plain", base)
    with_needs, _ = _client_for(f"guard_rep_{key}_needs", (*base, *report.needs))
    missing = [p for p in report.needs if p not in base]
    expect = 403 if missing else 200
    urls = {
        "page": reverse("reports:report", kwargs={"key": key}),
        "print": reverse("reports:print", kwargs={"key": key}),
        "excel": reverse("reports:excel", kwargs={"key": key}),
    }
    problems: list[str] = []
    for label, url in urls.items():
        got = without.get(url).status_code
        if got != expect:
            problems.append(f"{label} without {missing or 'the needs'}: {got}, expected {expect}")
        got = with_needs.get(url).status_code
        if got != 200:
            problems.append(f"{label} with the needs: {got}, expected 200")
    assert not problems, f"report {key}: " + "; ".join(problems)
