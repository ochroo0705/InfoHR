"""Help entries for the templates an admin keeps: the checklist templates and the order (Word) templates.

Like the saved report views (areas/saved_views.py) these are built for each question: an admin adds, renames, switches
off and fills in checklist templates, and uploads their own order file, so what each template holds is read from the
database now, not written here. They are not in `ENTRIES` or `ENTRY_BY_KEY`; `allowed_entries` adds them.

Keys: `checklist.template.<pk>` and `order.template.<order type number>`.
Rights are those of the general entries: checklist templates need checklists.manage_checklists; order templates need
the admin site (staff) and the view or change right of the order template model.
"""

from datetime import date

from accounts.models import User
from checklists.models import ChecklistKind, ChecklistTemplate
from employees.models import OrderTemplate, OrderType

from assistant.entry import HelpEntry

CHECKLIST_PREFIX = "checklist.template."
ORDER_PREFIX = "order.template."
MAX_TEMPLATES = 50  # checklist templates, in the admin list's order
MAX_TASKS = 12  # tasks named in one entry; a longer template says how many more there are


def entries_for(user: User, day: date) -> list[HelpEntry]:
    """The template entries `user` may be shown."""
    return [*_checklist_entries(user), *_order_entries(user)]


def _manages_checklists(user: User, day: date) -> bool:
    return user.has_perm("checklists.manage_checklists")


def _edits_order_templates(user: User, day: date) -> bool:
    return user.is_staff and any(
        user.has_perm(p) for p in ("employees.view_ordertemplate", "employees.change_ordertemplate")
    )


def _checklist_entries(user: User) -> list[HelpEntry]:
    if not _manages_checklists(user, date.min):
        return []
    templates = ChecklistTemplate.objects.prefetch_related("tasks").order_by("kind", "name")[:MAX_TEMPLATES]
    return [_checklist_entry(t) for t in templates]


def _checklist_entry(template: ChecklistTemplate) -> HelpEntry:
    kind = ChecklistKind(template.kind).label
    titles = [task.title for task in template.tasks.all()]
    shown = titles[:MAX_TASKS]
    if not titles:
        tasks = "Загварт одоогоор даалгавар алга."
    else:
        tasks = "Загварт дараах даалгаварууд байна: " + "; ".join(shown)
        tasks += f" ба өөр {len(titles) - len(shown)} даалгавар." if len(titles) > len(shown) else "."
    notes = []
    if not template.active:
        notes.append("Энэ загвар идэвхгүй тул шинэ жагсаалтад ашиглагдахгүй.")
    if template.is_default:
        notes.append(f"Энэ нь «{kind}» төрлийн үндсэн загвар: шалтгаан нь аль ч загварт байхгүй үед ашиглагдана.")
    return HelpEntry(
        key=f"{CHECKLIST_PREFIX}{template.pk}",
        title=f"«{template.name}» жагсаалтын загвар ({kind})",
        steps=(
            "Админы цэсийн «Тохиргоо» хэсгээс «Жагсаалтын загвар»-ыг сонгоно.",
            f"«{template.name}» загварыг нээнэ.",
            tasks,
        ),
        url_name="admin:checklists_checklisttemplate_change",
        modal=False,
        need=_manages_checklists,
        labels=("Тохиргоо", "Жагсаалтын загвар", template.name),
        words=(template.name, *shown),
        note=" ".join(notes),
        url_args=(str(template.pk),),
    )


def _order_entries(user: User) -> list[HelpEntry]:
    if not _edits_order_templates(user, date.min):
        return []
    rows = {row.order_type: row for row in OrderTemplate.objects.all()}
    return [_order_entry(OrderType(value), rows.get(value)) for value in OrderType.values]


def _order_entry(order_type: OrderType, row: OrderTemplate | None) -> HelpEntry:
    label = str(order_type.label)
    own = bool(row is not None and row.file)
    if own:
        note = "Одоо байгууллагын өөрийн оруулсан Word загвар ашиглагдаж байна."
    else:
        note = "Одоо стандарт загвар ашиглагдаж байна."
    return HelpEntry(
        key=f"{ORDER_PREFIX}{order_type.value}",
        title=f"«{label}» тушаалын загвар",
        steps=(
            "«Тохиргоо» хэсгээс Админ хэсэгт орж, «Тушаалын загварууд»-ыг нээнэ.",
            f"«{label}» мөрийг нээгээд Word (.docx) загвар файлаа оруулна. "
            "Файл оруулаагүй бол стандарт загвар ашиглагдана.",
            "«Хадгалах» дарна.",
        ),
        url_name="admin:employees_ordertemplate_change"
        if row is not None
        else "admin:employees_ordertemplate_changelist",
        modal=False,
        need=_edits_order_templates,
        labels=("Тохиргоо", "Тушаалын загварууд", label, "Хадгалах"),
        words=(f"{label} тушаал", f"{label} тушаалын загвар"),
        note=note,
        url_args=(str(row.pk),) if row is not None else (),
    )
