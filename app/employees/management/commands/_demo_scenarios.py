"""Scenario data for the demo database, run by seed_demo after the people exist.

Everything goes through the production services (events, orders, slots, recruitment pipeline, checklists, leave
requests), never straight into the tables, so the demo shows what the screens really produce. Dates are relative to
today, so «upcoming», «overdue» and «birthday this week» stay true whenever the demo is rebuilt.

What it adds on top of seed_demo's people: branches, budget slots (free, full, over-used, missing), signed, registered
and pending orders, events (transfer, promotion, long leave, termination with the offboarding checklist, pension,
contract change, scheduled, waiting for a signature, cancelled), recruitment (vacancies and candidates in every stage),
extra logins (auditor, branch-scoped HR, forced password change, inactive), an onboarding checklist and more leave
request states.
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from accounts.audit import Category, record_safe
from accounts.models import AccessScope, User
from accounts.roles import AUDITOR, HR
from checklists.models import ChecklistKind, ChecklistTask, ChecklistTemplate
from checklists.services import lifecycle, onboarding
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from leave.models import LeaveSettings
from leave.services import requests as leave_requests
from macs.models import Branch, FamilyRow, FiredReason, Position, PresentRow
from recruitment.models import Candidate, Stage, Vacancy, VacancyStatus
from recruitment.services import files as candidate_files
from recruitment.services import pipeline

from employees.models import CompanySettings, Employee, Event, EventType, HrOrder, OrderState
from employees.services import events, logins, macs_writes, orders, slots
from employees.slot_kind import MAIN, TEMPORARY

Ctx = dict[str, Any]


def run(ctx: Ctx) -> None:
    """Add every scenario. `ctx` carries what seed_demo built: people (by given name), branches, depts, positions,
    reasons, types (leave types), the users hr / director / accountant / system, today and list_entry."""
    ChecklistTemplate.objects.update(active=True)  # the starter templates, so the checklists below can start
    _children_and_gifts(ctx)
    _hire_orders(ctx)
    _events(ctx)
    _slots(ctx)
    _recruitment(ctx)
    _logins(ctx)
    _checklists(ctx)
    _leave_states(ctx)
    _audit_samples(ctx)


# ---- helpers ----


def _sign(event: Event, by: User) -> Event:
    """Give the event's order a number, date and signed scan, which applies the change that waited for it."""
    order = HrOrder.objects.filter(event=event).first()
    today = timezone.localdate()
    if order is not None and order.state == OrderState.PENDING:
        orders.register(order, number=orders.suggest_number(today), date=today, summary="", issued_by="Захирал", by=by)
        order.refresh_from_db()
    if order is not None and order.state == OrderState.REGISTERED:
        scan = SimpleUploadedFile("order.pdf", b"%PDF-1.4 demo order", content_type="application/pdf")
        orders.attach_signed_file(order, scan, by=by)
    event.refresh_from_db()
    if order is None and event.applied_at is None:
        events.apply_waiting(event, by=by)
        event.refresh_from_db()
    return event


def _record(emp: Employee, by: User, **kwargs: Any) -> Event:
    values: dict[str, Any] = {"changes": {}, "salary": None, "reason": "", "note": "", "by": by, **kwargs}
    return events.record(emp, **values)


# ---- children and gifts (reports A6, F2, F3) ----


def _children_and_gifts(ctx: Ctx) -> None:
    people, today = ctx["people"], ctx["today"]
    son = ctx["list_entry"](_model("FamilyRelation"), "Хүү", fm_type="son")
    daughter = ctx["list_entry"](_model("FamilyRelation"), "Охин", fm_type="daughter")
    kids = [
        ("Болд", son, "Бат-Эрдэнэ", 6),
        ("Болд", daughter, "Наран", 2),
        ("Ариунаа", daughter, "Сарнай", 4),
        ("Сарантуяа", son, "Тэмүүжин", 11),
        ("Сарантуяа", daughter, "Номин-Эрдэнэ", 15),
        ("Оюунчимэг", son, "Анхбаяр", 8),
    ]
    for parent, relation, name, age in kids:
        macs_writes.save_list_entry(
            FamilyRow,
            {
                "employee": people[parent],
                "relation": relation,
                "given_name": name,
                "birth_date": date(today.year - age, 3, 15),
            },
        )
    # One child already had this year's gift; the others still wait for one (the «gifts to give» report).
    gift = ctx["list_entry"](_model("PresentType"), "Мөнгөн бэлэг")
    macs_writes.save_list_entry(
        PresentRow,
        {
            "employee": people["Сарантуяа"],
            "childqty": 1,
            "price": 50000,
            "given_year": today.year,
            "pdate": today - timedelta(days=60),
            "present_type": gift,
            "child_age": 11,
            "given": 1,
        },
    )


def _model(name: str) -> Any:
    from macs import models

    return getattr(models, name)


# ---- hire orders: signed, registered, pending ----


def _hire_orders(ctx: Ctx) -> None:
    hr, today = ctx["hr"], ctx["today"]
    hires = list(HrOrder.objects.filter(is_hire=True).select_related("employee").order_by("pk"))
    for i, order in enumerate(hires):
        if i >= len(hires) - 3:
            continue  # the newest three stay without a number (pending)
        day = min(ctx["starts"].get(order.employee_id, today), today)
        orders.register(order, number=orders.suggest_number(day), date=day, summary="", issued_by="Захирал", by=hr)
        if i < len(hires) - 5:  # the rest are registered but not yet signed
            order.refresh_from_db()
            scan = SimpleUploadedFile("hire-order.pdf", b"%PDF-1.4 demo hire order", content_type="application/pdf")
            orders.attach_signed_file(order, scan, by=hr)


# ---- events ----


def _events(ctx: Ctx) -> None:
    p, d, pos, hr, today, accountant = (
        ctx["people"],
        ctx["depts"],
        ctx["positions"],
        ctx["hr"],
        ctx["today"],
        ctx["accountant"],
    )
    day = timedelta

    # Long leave with a return date (maternity), recorded as an event.
    _record(p["Ариунаа"], hr, type=EventType.LEAVE_START, effective=today - day(days=70), reason="maternity",
            expected_return=today + day(days=110))  # fmt: skip

    # A transfer and a promotion, both signed.
    _sign(_record(p["Ганзориг"], hr, type=EventType.TRANSFER, effective=today - day(days=150),
                  changes={"department": d["Програм хангамж"]}, note="Баг нэгтгэсэн"), hr)  # fmt: skip
    _sign(_record(p["Тэмүүлэн"], hr, type=EventType.PROMOTION, effective=today - day(days=60),
                  changes={"position": pos["Ахлах програм хөгжүүлэгч"]}, salary=Decimal("3400000"),
                  note="Жилийн үнэлгээгээр"), hr)  # fmt: skip

    # Contract extended; the person becomes a pensioner (pension on a contract change).
    _sign(_record(p["Дашдорж"], hr, type=EventType.CONTRACT, effective=today - day(days=100), pension=True,
                  changes={"contract_no": "ХГ25-099"}), hr)  # fmt: skip

    # A contract that ends soon (shown in «Анхаарах»).
    _record(p["Билгүүн"], hr, type=EventType.CONTRACT, effective=today - day(days=5),
            changes={"contract_no": "ХГ26-120", "contract_end": today + day(days=21)})  # fmt: skip

    # Scheduled (in the future, no order needed) and waiting for a signature (order registered, no scan yet).
    _record(p["Номин"], accountant, type=EventType.SALARY_CHANGE, effective=today + day(days=45),
            salary=Decimal("2900000"), note="Жилийн нэмэгдэл")  # fmt: skip
    waiting = _record(p["Ганзориг"], hr, type=EventType.PROMOTION, effective=today + day(days=10),
                      changes={"position": pos["Програм хөгжүүлэгч"]}, note="Багт шилжүүлэх")  # fmt: skip
    order = HrOrder.objects.filter(event=waiting).first()
    if order is not None:
        orders.register(order, number=orders.suggest_number(today), date=today, summary="Албан тушаал дэвшүүлэх",
                        issued_by="Захирал", by=hr)  # fmt: skip

    # A change recorded and then cancelled.
    cancelled = _record(p["Ариунаа"], hr, type=EventType.SALARY_CHANGE, effective=today + day(days=30),
                        salary=Decimal("3700000"))  # fmt: skip
    events.cancel(cancelled, reason="Буруу дүн оруулсан", by=hr)

    # A leaver: the offboarding checklist is ticked through, the termination is signed.
    leaver = p["Мөнх-Эрдэнэ"]
    reason: FiredReason = ctx["reasons"]["Өөрийн хүсэлтээр"]
    last_day = today - day(days=180)
    checklist = lifecycle.start(leaver, ChecklistKind.OFFBOARDING, reason=str(reason.pk), anchor_day=last_day, by=hr)
    if checklist is not None:
        for task in ChecklistTask.objects.filter(checklist=checklist):
            lifecycle.tick(task, by=hr)
    _sign(_record(leaver, hr, type=EventType.TERMINATION, effective=last_day, fired_reason=reason,
                  note="Өөрийн хүсэлтээр"), hr)  # fmt: skip

    # A second leaver whose offboarding is still open: ticked halfway, not yet terminated.
    pending_leaver = p["Хулан"]
    started = lifecycle.start(
        pending_leaver, ChecklistKind.OFFBOARDING, reason=None, anchor_day=today + day(days=14), by=hr
    )
    if started is not None:
        first = ChecklistTask.objects.filter(checklist=started).order_by("position").first()
        if first is not None:
            lifecycle.tick(first, by=hr)


# ---- position slots ----


def _slots(ctx: Ctx) -> None:
    """Budget rows for this year in every state, then the switch on. Used counts come from the hired people."""
    today, hr = ctx["today"], ctx["hr"]
    used = slots.used_by_key(today.year, today)
    positions = {pk: obj for pk, obj in ((o.pk, o) for o in Position.objects.all())}
    branches = {b.pk: b for b in Branch.objects.all()}
    skip = {ctx["positions"]["Жолооч"].pk}  # no row at all: «no row = zero posts»
    over = {ctx["positions"]["Борлуулалтын менежер"].pk}  # used beyond the posts (an override happened)
    full = {ctx["positions"]["Гүйцэтгэх захирал"].pk, ctx["positions"]["Хүний нөөцийн менежер"].pk}
    for (position_id, branch_id, kind), count in sorted(
        used.items(), key=lambda kv: (kv[0][0], kv[0][1] or 0, kv[0][2])
    ):
        if position_id in skip or branch_id is None:
            continue
        if position_id in over:
            qty = max(count - 1, 0)
        elif position_id in full:
            qty = count
        else:
            qty = count + 2 if kind == MAIN else count + 1
        slots.save_row(position=positions[position_id], branch=branches[branch_id], kind=kind, year=today.year,
                       qty=qty, by=hr)  # fmt: skip
    # An unused row (free posts nobody holds) and last year's rows, for the year switch on the screen.
    spare = ctx["positions"]["Програм хөгжүүлэгч"]
    slots.save_row(position=spare, branch=ctx["branches"]["Төв салбар"], kind=TEMPORARY, year=today.year, qty=2, by=hr)
    slots.save_row(position=spare, branch=ctx["branches"]["Төв салбар"], kind=MAIN, year=today.year - 1, qty=3, by=hr)
    settings = CompanySettings.get()
    settings.enforce_position_slots = True
    settings.save()


# ---- recruitment ----


def _recruitment(ctx: Ctx) -> None:
    hr, today, p, d, pos, branches = (
        ctx["hr"],
        ctx["today"],
        ctx["people"],
        ctx["depts"],
        ctx["positions"],
        ctx["branches"],
    )
    bold_user = ctx["users"]["Болд"]
    centre = branches["Төв салбар"]

    def vacancy(title: str, position: str, dept: str, **extra: Any) -> Vacancy:
        return Vacancy.objects.create(title=title, position=pos[position], department=d[dept], created_by=hr, **extra)

    dev = vacancy(
        "Програм хөгжүүлэгч (2 хүн)",
        "Програм хөгжүүлэгч",
        "Програм хангамж",
        branch=centre,
        headcount=2,
        hiring_manager=p["Болд"],
        deadline=today + timedelta(days=30),
        desired_start=today + timedelta(days=45),
        description="Python, Django мэдлэгтэй, багаар ажиллах чадвартай.",
    )
    sales = vacancy(
        "Борлуулалтын менежер",
        "Борлуулалтын менежер",
        "Борлуулалт",
        branch=centre,
        headcount=1,
        hiring_manager=p["Ариунаа"],
        deadline=today + timedelta(days=14),
    )
    vacancy(
        "Жолооч",
        "Жолооч",
        "Удирдлага",
        branch=centre,
        headcount=1,
        status=VacancyStatus.CLOSED,
        description="Төсөв батлагдаагүй тул хаасан.",
    )
    office = vacancy(
        "Оффисын менежер",
        "Оффисын менежер",
        "Удирдлага",
        branch=centre,
        headcount=1,
        desired_start=today + timedelta(days=14),
    )
    vacancy(
        "Нягтлан бодогч (салбар тодорхойгүй)", "Нягтлан бодогч", "Санхүү", headcount=1
    )  # no branch: the line asks for one

    def candidate(
        v: Vacancy, surname: str, given: str, stage: str | None = None, source: str = "Вэбсайт", **extra: str
    ) -> Candidate:
        c = pipeline.add_candidate(
            v, by=hr, surname=surname, given_name=given, source=source, phone="99000000", **extra
        )
        if stage in (Stage.SCREENING, Stage.INTERVIEW, Stage.OFFER):
            for step in (Stage.SCREENING, Stage.INTERVIEW, Stage.OFFER):
                pipeline.move(c, step, by=hr)
                if step == stage:
                    break
        return c

    candidate(dev, "Гантулга", "Эрдэнэ", Stage.NEW, email="erdene@example.mn")
    shortlisted = candidate(dev, "Бат-Очир", "Саруул", Stage.SCREENING, source="Танилын санал")
    interviewing = candidate(dev, "Лхагвасүрэн", "Төмөр", Stage.INTERVIEW, notes="Туршлага 4 жил")
    offered = candidate(dev, "Мягмар", "Золзаяа", Stage.OFFER)
    declined = candidate(dev, "Доржсүрэн", "Анужин", Stage.INTERVIEW)
    pipeline.reject(declined, by=hr, reason="Цалингийн хүлээлт таарсангүй")
    quit_ = candidate(dev, "Ширнэн", "Билгүүн", Stage.SCREENING)
    pipeline.reject(quit_, by=hr, reason="", withdrawn=True)
    pipeline.comment(shortlisted, by=hr, text="CV сайн. Техникийн ярилцлагад урих.")
    pipeline.comment(interviewing, by=bold_user, text="Техникийн даалгавар сайн биелүүлсэн.")
    pipeline.comment(offered, by=hr, text="Санал илгээсэн, хариу хүлээж байна.")
    candidate_files.save(shortlisted, SimpleUploadedFile("cv-saruul.pdf", b"%PDF-1.4 demo cv"), by=hr)

    candidate(sales, "Энхтүвшин", "Оюун", Stage.NEW)
    candidate(sales, "Пүрэвдорж", "Цэцэг", Stage.SCREENING)

    # One candidate already hired: it is the upcoming hire, so that vacancy is filled.
    hired = candidate(office, "Энхтайваны", "Хулан", Stage.OFFER)
    pipeline.mark_hired(hired, p["Хулан"], by=hr)

    # An old closed candidate, past the retention period: the purge screen has something to remove.
    old = candidate(sales, "Алтан", "Хуучин")
    pipeline.reject(old, by=hr, reason="Хуучин өргөдөл")
    Candidate.objects.filter(pk=old.pk).update(closed_at=timezone.now() - timedelta(days=900))


# ---- logins ----


def _logins(ctx: Ctx) -> None:
    hr, p, branches = ctx["hr"], ctx["people"], ctx["branches"]

    # The auditor: sees the system log only, no employee data.
    auditor = User.objects.create_user("auditor", password=ctx["password"], first_name="Хяналтын", last_name="Ажилтан")
    auditor.groups.add(Group.objects.get(name=AUDITOR))

    # A branch-limited HR login: sees only the people of its branch.
    scoped = User.objects.create_user("darkhan_hr", password=ctx["password"], first_name="Билгүүн", last_name="Дархан")
    scoped.groups.add(Group.objects.get(name=HR))
    AccessScope.objects.create(user=scoped, limited=True, branch_ids=[branches["Дархан салбар"].pk])

    # A login created by HR with a temporary password: must change it at first sign-in.
    logins.create_login(p["Тэмүүлэн"], "temuulen", by=hr)

    # A login of someone who left: inactive.
    leaver_user, _password = logins.create_login(p["Мөнх-Эрдэнэ"], "munkh_erdene", by=hr)
    leaver_user.is_active = False
    leaver_user.save(update_fields=["is_active"])


# ---- onboarding ----


def _checklists(ctx: Ctx) -> None:
    hr, p, today = ctx["hr"], ctx["people"], ctx["today"]
    upcoming = onboarding.start_for_hire(
        p["Хулан"], start_date=today + timedelta(days=14), employee_type="full_time", by=hr
    )
    if upcoming is not None:
        first = ChecklistTask.objects.filter(checklist=upcoming).order_by("position").first()
        if first is not None:
            lifecycle.tick(first, by=hr)
    # The intern started 40 days ago: an onboarding that is overdue.
    onboarding.start_for_hire(p["Анар"], start_date=today - timedelta(days=40), employee_type="intern", by=hr)


# ---- leave states ----


def _leave_states(ctx: Ctx) -> None:
    hr, today, p, types = ctx["hr"], ctx["today"], ctx["people"], ctx["types"]
    director_user = ctx["users"]["Энхбаяр"]
    bold_user = ctx["users"]["Болд"]
    LeaveSettings.objects.update_or_create(pk=1, defaults={"approval1_manager": True})
    base = today + timedelta(days=60)
    base += timedelta(days=(7 - base.weekday()) % 7)  # a Monday

    def submit(emp: Employee, by: User, kind: str, start: date, days: int, note: str = "") -> Any:
        end = start + timedelta(days=days - 1)
        if leave_requests.preview(emp, types[kind], start, end, today).errors:
            return None
        return leave_requests.submit(emp, types[kind], start, end, note, by, today)

    approved = submit(p["Тэмүүлэн"], hr, "annual", base, 5, "Зуны амралт")
    if approved is not None:
        leave_requests.approve(approved, director_user, today)
    taken_back = submit(p["Болд"], bold_user, "personal", base + timedelta(days=14), 1, "Хувийн асуудал")
    if taken_back is not None:
        leave_requests.withdraw(taken_back, bold_user, today)
    declined = submit(p["Оюунчимэг"], hr, "unpaid", base + timedelta(days=21), 1, "Хувийн хэрэг")
    if declined is not None:
        leave_requests.reject(declined, director_user, "Тухайн үед ажлын ачаалал их байна", today)
    submit(p["Ганзориг"], hr, "sick", today + timedelta(days=3), 2, "Эмчийн үзлэг")  # waits for the manager


# ---- audit samples ----


def _audit_samples(ctx: Ctx) -> None:
    """Log lines the services above do not produce on their own (sign-ins and exports come from real requests)."""
    hr = ctx["hr"]
    for category, action, message in (
        (Category.ACCESS, "login", "Амжилттай нэвтэрсэн"),
        (Category.ACCESS, "login_failed", "Нууц үг буруу: hr"),
        (Category.EXPORT, "export_list", "Ажилтны жагсаалт Excel-ээр татсан"),
        (Category.EXPORT, "export_report", "Нас, хүүхдийн тайлан Excel-ээр татсан"),
    ):
        record_safe(category, action, actor=hr, message=message)
