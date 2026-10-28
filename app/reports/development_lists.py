"""The development-tab lists: D1 the trainings of a period, D2 the skill tasks of a period, D3 the health checks of a
period, F4 the client complaints of a period.

Rows come from the production `hr_training`, `hr_skillwork`, `body` and `hr_complaints` tables. Each row is paired
with its person's listing row for today (personal_lists.with_rows), so the department and position come from the same
service as the screens. A row with no date cannot sit in a period, so a training without a start date is left out.
The lists need the personal-tab right, as B5 and B6 do.
"""

from datetime import timedelta

from accounts.models import User
from django.utils import timezone
from employees.services.order_register import age_on
from employees.services.personal_writes import COMPLAINT_KINDS, COMPLAINT_TYPES, PAY_TYPES, TR_TYPES
from macs.models import BodyRow, ComplaintRow, SkillWorkRow, TrainingRow

from reports.filters import Filters, period_of
from reports.personal_lists import (
    NEEDS,
    PERSON_COLUMNS,
    ListRow,
    detail_url,
    full_name,
    or_none,
    people,
    with_rows,
)
from reports.staff_list import kept_rows
from reports.types import Column, Report


def _training_rows(user: User, f: Filters) -> list[ListRow]:
    """D1: the trainings that start in the period, of the people the user may see, sorted by start date then name."""
    start, end = period_of(f)
    items = TrainingRow.objects.filter(
        employee__in=people(user),
        start_date__gte=start,
        start_date__lt=end + timedelta(days=1),
    )
    if f.tr_type is not None:
        items = items.filter(tr_type=f.tr_type)
    found = with_rows(list(items), timezone.localdate())
    return sorted(found, key=lambda r: (r.item.start_date, full_name(r)))


def _health_rows(user: User, f: Filters) -> list[ListRow]:
    """D3: the health checks dated in the period, of the working people the user may see, sorted by date then name.
    «Working» is the staff list's own test (kept_rows with the default state), so both reports count the same people."""
    start, end = period_of(f)
    working = [r.employee.pk for r in kept_rows(user, Filters())[0]]
    items = BodyRow.objects.filter(
        employee_id__in=working,
        inserted_ognoo__gte=start,
        inserted_ognoo__lt=end + timedelta(days=1),
    )
    found = with_rows(list(items), timezone.localdate())
    return sorted(found, key=lambda r: (r.item.inserted_ognoo, full_name(r)))


def _skill_task_rows(user: User, f: Filters) -> list[ListRow]:
    """D2: the skill tasks dated in the period, of the people the user may see. The department filter is the task's own
    department (the old query joins the task's dep_ident), so a task keeps its department whoever it was given to."""
    start, end = period_of(f)
    items = SkillWorkRow.objects.select_related("department").filter(
        employee__in=people(user),
        sdate__gte=start,
        sdate__lt=end + timedelta(days=1),
    )
    if f.department is not None:
        items = items.filter(department_id=f.department)
    found = with_rows(list(items), timezone.localdate())
    return sorted(found, key=lambda r: (r.item.sdate, full_name(r)))


def _complaint_rows(user: User, f: Filters) -> list[ListRow]:
    """F4: the client complaints dated in the period, of the people the user may see, sorted by date then name."""
    start, end = period_of(f)
    items = ComplaintRow.objects.filter(
        employee__in=people(user),
        cdate__gte=start,
        cdate__lt=end + timedelta(days=1),
    )
    found = with_rows(list(items), timezone.localdate())
    return sorted(found, key=lambda r: (r.item.cdate, full_name(r)))


def _task_department(r: ListRow) -> str | None:
    """The department the task was recorded against; None when the task has none."""
    return r.item.department.name if r.item.department_id is not None else None


def _age_today(r: ListRow) -> int | None:
    """The person's full age today; None when there is no birth date."""
    return age_on(r.row.employee.birth_date, timezone.localdate())


def _text(key: str, label: str) -> Column:
    """A health-check finding: the text the doctor wrote, or an empty cell."""
    return Column(key=key, label=label, value=lambda r: or_none(getattr(r.item, key)))


def _note(f: Filters) -> str:
    """The grey line: the department and position are today's, whatever the period."""
    return "Хэлтэс, албан тушаал нь ажилтны өнөөдрийн ажил."


def _skill_task_note(f: Filters) -> str:
    """The grey line: the task's department is the one it was recorded against, not the person's."""
    return "Хэлтэс нь даалгаварт бүртгэсэн хэлтэс."


TRAINING_COLUMNS: tuple[Column, ...] = (
    Column(key="date", label="Огноо", value=lambda r: r.item.start_date),
    *PERSON_COLUMNS,
    Column(key="type", label="Хэлбэр", value=lambda r: TR_TYPES.get(r.item.tr_type)),
    Column(key="description", label="Сургалтын нэр", value=lambda r: r.item.description),
    Column(key="days", label="Хоног", value=lambda r: r.item.days, numeric=True),
    Column(key="amount", label="Төлбөр", value=lambda r: r.item.amount, numeric=True, money=True),
    Column(key="pay_type", label="Төлсөн хэлбэр", value=lambda r: PAY_TYPES.get(r.item.pay_type)),
    Column(key="center", label="Сургалтын төв", value=lambda r: or_none(r.item.training_center)),
)

SKILL_TASK_COLUMNS: tuple[Column, ...] = (
    Column(key="date", label="Огноо", value=lambda r: r.item.sdate),
    Column(key="code", label="Код", value=lambda r: r.row.employee.code),
    Column(key="name", label="Ажилтан", value=full_name, href=detail_url),
    Column(key="task_department", label="Хэлтэс", value=_task_department),
    Column(key="description", label="Даалгавар", value=lambda r: or_none(r.item.description)),
    Column(key="norm", label="Нормын тоо", value=lambda r: r.item.norm, numeric=True),
    Column(key="comment", label="Тайлбар", value=lambda r: or_none(r.item.comment)),
)

COMPLAINT_COLUMNS: tuple[Column, ...] = (
    Column(key="date", label="Огноо", value=lambda r: r.item.cdate),
    *PERSON_COLUMNS,
    Column(key="type", label="Төрөл", value=lambda r: COMPLAINT_TYPES.get(r.item.ctype)),
    Column(key="kind", label="Гомдол", value=lambda r: COMPLAINT_KINDS.get(r.item.complaint_name)),
    Column(key="comment", label="Тайлбар", value=lambda r: or_none(r.item.comment)),
)

HEALTH_COLUMNS: tuple[Column, ...] = (
    Column(key="date", label="Үзлэгийн огноо", value=lambda r: r.item.inserted_ognoo),
    *PERSON_COLUMNS,
    Column(key="gender", label="Хүйс", value=lambda r: or_none(r.row.employee.get_gender_display())),
    Column(key="age", label="Нас", value=_age_today, numeric=True),
    Column(key="term_type", label="Үзлэгийн төрөл", value=lambda r: or_none(r.item.term_type)),
    Column(key="end_date", label="Дуусах хугацаа", value=lambda r: r.item.end_date),
    _text("own_letter", "Өөрийн мэдүүлэг"),
    _text("ear", "Чих хамар хоолой"),
    _text("dotor", "Дотор"),
    _text("medrel", "Мэдрэл"),
    _text("setgel_medrel", "Сэтгэл мэдрэл"),
    _text("mes_zasal", "Мэс засал"),
    _text("nud", "Нүд"),
    _text("female", "Эмэгтэйчүүд"),
    _text("rentgen", "Рентген"),
    _text("skin", "Арьс"),
    _text("conclusion", "Дүгнэлт"),
)


TRAINING = Report(
    key="training",
    title="Сургалтын тайлан",
    filters=("tr_type", "period"),
    columns=TRAINING_COLUMNS,
    default_columns=tuple(c.key for c in TRAINING_COLUMNS),
    rows=_training_rows,
    needs=NEEDS,
    source=TrainingRow,
    group_options=("type", "department"),
    note=_note,
)

HEALTH_CHECKS = Report(
    key="health-checks",
    title="Эрүүл мэндийн үзлэгт хамрагдсан тайлан",
    filters=("period",),
    columns=HEALTH_COLUMNS,
    default_columns=tuple(c.key for c in HEALTH_COLUMNS),
    rows=_health_rows,
    needs=NEEDS,
    source=BodyRow,
    group_options=("department",),
    note=_note,
)

SKILL_TASKS = Report(
    key="skill-tasks",
    title="Ур чадварын даалгавар",
    filters=("department", "period"),
    columns=SKILL_TASK_COLUMNS,
    default_columns=tuple(c.key for c in SKILL_TASK_COLUMNS),
    rows=_skill_task_rows,
    needs=NEEDS,
    source=SkillWorkRow,
    group_options=("task_department",),
    note=_skill_task_note,
)

COMPLAINTS = Report(
    key="complaints",
    title="Үйлчлүүлэгчийн санал, гомдлын тайлан",
    filters=("period",),
    columns=COMPLAINT_COLUMNS,
    default_columns=tuple(c.key for c in COMPLAINT_COLUMNS),
    rows=_complaint_rows,
    needs=NEEDS,
    source=ComplaintRow,
    group_options=("type", "department"),
    note=_note,
)
