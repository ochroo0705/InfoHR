"""The screens of the staff Excel import: upload, column map, preview, run and result. Plain forms and redirects, no
htmx. Every page needs the manage right; a draft's pages are open only to the user who uploaded it and to Admin."""

from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import quote

from accounts.audit import record_export
from accounts.models import User
from accounts.roles import ADMIN
from django import forms
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from macs.models import Country, Department, Position

from employees import access
from employees.forms import StyledForm
from employees.models import STAFF_IMPORT_DATE_FORMATS, StaffImportDraft, StaffImportSettings
from employees.staff_import import matching, plan, reader, run, template
from employees.staff_import.fields import BY_KEY, FIELDS
from employees.staff_import.rows import DATE_FORMATS

CONFIRM_ABOVE = 20  # more new people than this: the user must type the count
PREVIEW_ROWS = 100
RETENTION = timedelta(days=7)
RECENT_LIMIT = 10
HEADER_ROWS = range(1, 11)
DEFAULT_KEYS = ("start", "department", "position", "branch", "citizenship", "work_conditions")
WORK_CONDITION_CHOICES = ("Хэвийн", "Хүнд", "Бусад")
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
REJECTED_NAME = "алдаатай-мөрүүд.xlsx"
TEMPLATE_NAME = "ajiltan-zagvar.xlsx"
UNFINISHED = "Импорт дуусаагүй байна. Файлыг дахин оруулна уу."
IN_PROGRESS = "Импорт явагдаж байна. Хэдэн секундын дараа хуудсаа шинэчилнэ үү."
PREVIEW_ERRORS = {
    "count": "Ажилтны тоо таарахгүй байна. Импорт хийгдсэнгүй. Тоог дахин бичнэ үү.",
    "none": "Импорт хийх шинэ ажилтан алга.",
    "claimed": "Энэ файлыг аль хэдийн импортолж байна эсвэл импортолсон байна.",
    "file": "Файлыг уншиж чадсангүй. Файлыг дахин оруулна уу.",
    "busy": IN_PROGRESS,
}
STATUS_LOOK = {
    "new": ("Шинэ", "bg-emerald-100 text-emerald-800"),
    "duplicate": ("Давхардсан", "bg-amber-100 text-amber-900"),
    "error": ("Алдаатай", "bg-red-50 text-red-700 ring-1 ring-inset ring-red-200"),
}


class UploadForm(StyledForm):
    file = forms.FileField(
        label="Excel файл (.xlsx)",
        error_messages={"required": "Файлаа сонгоно уу."},
    )

    def clean_file(self) -> Any:
        upload = self.cleaned_data["file"]
        if not upload.name.lower().endswith(".xlsx"):
            raise ValidationError("Зөвхөн .xlsx файл оруулна уу.")
        if upload.size is not None and upload.size > reader.MAX_BYTES:
            raise ValidationError(f"Файл хэт том байна. Дээд хэмжээ {reader.MAX_BYTES // (1024 * 1024)} МБ.")
        return upload


def _user(request: HttpRequest) -> User:
    assert isinstance(request.user, User)
    return request.user


def _is_admin(user: User) -> bool:
    return user.groups.filter(name=ADMIN).exists()


def _manager(request: HttpRequest) -> User:
    user = _user(request)
    if not access.can_manage(user):
        raise PermissionDenied
    return user


def _draft(request: HttpRequest, pk: Any) -> StaffImportDraft:
    """The draft, if the user may see it: its creator or an Admin. Anyone else gets 404."""
    user = _manager(request)
    draft = get_object_or_404(StaffImportDraft, pk=pk)
    if draft.created_by_id != user.pk and not _is_admin(user):
        raise Http404
    return draft


def _names(qs: Any) -> list[str]:
    return [name for name in qs.values_list("name", flat=True) if name and name.strip()]


def _iso(text: str, date_format: str) -> str:
    """A stored start date in the draft's format, as the ISO value a date box shows. Empty when it does not read."""
    pattern = DATE_FORMATS.get(date_format, DATE_FORMATS["iso"])[1]
    try:
        return datetime.strptime(text, pattern).date().isoformat()
    except ValueError:
        return ""


def _unfinished_redirect(draft: StaffImportDraft) -> HttpResponse | None:
    """Where a draft that is not in its upload state goes: a finished one to its result, a running one to the
    preview, which shows the unfinished message."""
    if draft.state == "imported":
        return redirect("employees:import_result", pk=draft.pk)
    if draft.state == "running":
        return redirect("employees:import_preview", pk=draft.pk)
    return None


def _upload_page(request: HttpRequest, user: User, form: UploadForm, notice: str = "") -> HttpResponse:
    recent = StaffImportDraft.objects.filter(created_by=user, state="imported").order_by("-finished_at")[:RECENT_LIMIT]
    return render(request, "employees/import_upload.html", {"form": form, "recent": recent, "notice": notice})


def _purge_old_drafts() -> None:
    """Abandoned drafts older than RETENTION are deleted with their staff data. An import that finished is kept as the
    record of what was imported; only its rejected-rows file (which holds staff data) is dropped."""
    cutoff = timezone.now() - RETENTION
    StaffImportDraft.objects.filter(created_at__lt=cutoff).exclude(state="imported").delete()
    StaffImportDraft.objects.filter(created_at__lt=cutoff, state="imported").update(data=b"", rejected_file=None)


def _first_staff_sheet(data: bytes) -> str:
    """The first sheet that has staff rows. An empty sheet is skipped; if none has rows, the no-data error is raised."""
    for name in reader.sheet_names(data):
        try:
            reader.read_rows(data, name, 1)
        except reader.ImportFileError as exc:
            if str(exc) != reader.NO_DATA:
                raise
            continue
        return name
    raise reader.ImportFileError(reader.NO_DATA)


@login_required
def import_upload(request: HttpRequest) -> HttpResponse:
    user = _manager(request)
    _purge_old_drafts()
    if request.method != "POST":
        return _upload_page(request, user, UploadForm())
    form = UploadForm(request.POST, request.FILES)
    if form.is_valid():
        upload = form.cleaned_data["file"]
        data = upload.read()
        try:
            sheet = _first_staff_sheet(data)  # refuse a file with no staff rows here, not on the next screen
        except reader.ImportFileError as exc:
            form.add_error("file", str(exc))
        else:
            draft = StaffImportDraft.objects.create(created_by=user, filename=upload.name[:200], data=data, sheet=sheet)
            return redirect("employees:import_map", pk=draft.pk)
    return _upload_page(request, user, form)


def _choices(user: User) -> dict[str, list[str]]:
    return {
        "departments": _names(Department.objects.exclude(ext__active=False).order_by("name")),
        "positions": _names(Position.objects.exclude(ext__active=False).order_by("name")),
        "branches": _names(access.branch_choices(user).order_by("name")),
        "countries": _names(Country.objects.order_by("name")),
    }


def _ignored(headings: list[str], mapping: dict[str, str], remembered: dict[str, str]) -> list[str]:
    """Headings of the salary columns this user does not import. A column mapped to a salary field is one; so is a
    column with no mapping whose heading looks like a salary field. A column the user kept for another field is not."""
    found: list[str] = []
    for index, heading in enumerate(headings):
        key = mapping.get(str(index))
        if key is not None:
            if key in BY_KEY and BY_KEY[key].needs_salary:
                found.append(heading)
        elif matching.ignored_salary_headings([heading], remembered=remembered):
            found.append(heading)
    return found


def _render_map(
    request: HttpRequest,
    draft: StaffImportDraft,
    headings: list[str],
    *,
    mapping: dict[str, str],
    defaults: dict[str, str],
    start: str,
    date_format: str,
    sheet: str,
    header_rows: int,
    errors: list[str] | None = None,
    missing: list[str] | None = None,
) -> HttpResponse:
    user = _user(request)
    allow_salary = access.can_manage_salary(user)
    settings_row = StaffImportSettings.get()
    shown = {index: key for index, key in mapping.items() if allow_salary or not BY_KEY[key].needs_salary}
    columns = [
        {
            "index": index,
            "label": heading or f"Багана {index + 1}",
            "key": shown.get(str(index), ""),
        }
        for index, heading in enumerate(headings)
    ]
    context: dict[str, Any] = {
        "draft": draft,
        "sheet": sheet,
        "sheet_names": reader.sheet_names(bytes(draft.data)),
        "header_rows": header_rows,
        "header_range": HEADER_ROWS,
        "columns": columns,
        "fields": [field for field in FIELDS if allow_salary or not field.needs_salary],
        "defaults": {key: (start if key == "start" else defaults.get(key, "")) for key in DEFAULT_KEYS},
        "date_formats": STAFF_IMPORT_DATE_FORMATS,
        "date_format": date_format,
        "work_condition_choices": WORK_CONDITION_CHOICES,
        "ignored": [] if allow_salary else _ignored(headings, mapping, settings_row.mapping),
        "errors": errors or [],
        "missing": missing or [],
        "allow_salary": allow_salary,
        **_choices(user),
    }
    return render(request, "employees/import_map.html", context)


@login_required
def import_map(request: HttpRequest, pk: Any) -> HttpResponse:
    user = _user(request)
    draft = _draft(request, pk)
    closed = _unfinished_redirect(draft)
    if closed is not None:
        return closed
    try:
        headings, _ = reader.read_rows(bytes(draft.data), draft.sheet, draft.header_rows)
    except reader.ImportFileError as exc:
        return _upload_page(request, user, UploadForm(), notice=str(exc))

    if request.method == "POST":
        if request.POST.get("action") == "reread":
            return _reread(request, draft, headings)
        return _save_map(request, draft, headings)

    allow_salary = access.can_manage_salary(user)
    settings_row = StaffImportSettings.get()
    if draft.mapping:  # the mapping was saved before: show what was saved
        mapping = dict(draft.mapping)
        defaults = dict(draft.defaults)
        date_format = draft.date_format
    else:  # first visit: guess the columns from the headings and the last import
        mapping = matching.auto_match(headings, remembered=settings_row.mapping, allow_salary=allow_salary)
        defaults = {key: value for key, value in settings_row.defaults.items() if key != "start"}
        date_format = settings_row.date_format
    start = _iso(str(draft.defaults.get("start", "")), draft.date_format) if draft.mapping else ""
    return _render_map(
        request,
        draft,
        headings,
        mapping=mapping,
        defaults=defaults,
        start=start,
        date_format=date_format,
        sheet=draft.sheet,
        header_rows=draft.header_rows,
    )


def _reread(request: HttpRequest, draft: StaffImportDraft, headings: list[str]) -> HttpResponse:
    """Another sheet or another number of heading rows: the headings are read again, so the old mapping is dropped."""
    sheet = request.POST.get("sheet", "")
    header_text = request.POST.get("header_rows", "")
    header_rows = int(header_text) if header_text.isdecimal() else 0
    if sheet not in reader.sheet_names(bytes(draft.data)) or header_rows not in HEADER_ROWS:
        return _render_map(
            request,
            draft,
            headings,
            mapping=dict(draft.mapping),
            defaults=dict(draft.defaults),
            start=_iso(str(draft.defaults.get("start", "")), draft.date_format),
            date_format=draft.date_format,
            sheet=draft.sheet,
            header_rows=draft.header_rows,
            errors=["Хуудас эсвэл толгой мөрийн тоо буруу байна."],
        )
    draft.sheet = sheet
    draft.header_rows = header_rows
    draft.mapping = {}
    draft.save(update_fields=["sheet", "header_rows", "mapping"])
    return redirect("employees:import_map", pk=draft.pk)


def _posted_mapping(post: Any, headings: list[str], allow_salary: bool) -> tuple[dict[str, str], list[str]]:
    """{column index as str: field key} from the form. Blank columns and salary fields the user may not use are
    left out; a field chosen for two columns is an error."""
    mapping: dict[str, str] = {}
    errors: list[str] = []
    for index in range(len(headings)):
        key = post.get(f"col_{index}", "")
        if not key:
            continue
        if key not in BY_KEY:
            errors.append("Талбарын сонголт буруу байна.")
            continue
        if BY_KEY[key].needs_salary and not allow_salary:
            continue
        if key in mapping.values():
            errors.append(f"«{BY_KEY[key].label}» талбарыг хоёр баганад холбосон байна.")
            continue
        mapping[str(index)] = key
    return mapping, errors


def _posted_defaults(post: Any, date_format: str, choices: dict[str, list[str]]) -> tuple[dict[str, str], list[str]]:
    """The fixed values from the form, in the form the import reads them: the start date in the chosen date format."""
    defaults: dict[str, str] = {}
    errors: list[str] = []
    for key in DEFAULT_KEYS:
        value = post.get(f"default_{key}", "").strip()
        if not value:
            continue
        if key == "start":
            try:
                value = date.fromisoformat(value).strftime(DATE_FORMATS[date_format][1])
            except ValueError:
                errors.append("Анх ажилд орсон огноо буруу байна.")
                continue
        elif key == "branch" and value not in choices["branches"]:
            errors.append("Салбар буруу байна.")
            continue
        elif key == "citizenship" and value not in choices["countries"]:
            errors.append("Иргэншил буруу байна.")
            continue
        elif key == "work_conditions" and value not in WORK_CONDITION_CHOICES:
            errors.append("Ажлын нөхцөл буруу байна.")
            continue
        defaults[key] = value
    return defaults, errors


def _save_map(request: HttpRequest, draft: StaffImportDraft, headings: list[str]) -> HttpResponse:
    allow_salary = access.can_manage_salary(_user(request))
    settings_row = StaffImportSettings.get()
    mapping, errors = _posted_mapping(request.POST, headings, allow_salary)
    date_format = request.POST.get("date_format", "")
    if date_format not in DATE_FORMATS:
        errors.append("Огнооны хэлбэр буруу байна.")
        date_format = draft.date_format
    defaults, default_errors = _posted_defaults(request.POST, date_format, _choices(_user(request)))
    errors += default_errors
    missing = matching.missing_required(mapping, defaults)
    if errors or missing:
        # Show what the user typed, not the converted values, so nothing typed is lost.
        posted = {key: request.POST.get(f"default_{key}", "").strip() for key in DEFAULT_KEYS}
        return _render_map(
            request,
            draft,
            headings,
            mapping=mapping,
            defaults={key: value for key, value in posted.items() if key != "start"},
            start=posted["start"],
            date_format=date_format,
            sheet=draft.sheet,
            header_rows=draft.header_rows,
            errors=errors,
            missing=missing,
        )

    draft.mapping = mapping
    draft.defaults = defaults
    draft.date_format = date_format
    draft.save(update_fields=["mapping", "defaults", "date_format"])
    # A start date is for one import only, so it is not remembered for the next one.
    remembered = {key: value for key, value in defaults.items() if key != "start"}
    matching.remember(settings_row, headings, mapping, remembered, date_format)
    return redirect("employees:import_preview", pk=draft.pk)


@login_required
def import_preview(request: HttpRequest, pk: Any) -> HttpResponse:
    user = _user(request)
    draft = _draft(request, pk)
    if draft.state == "running":
        # A run that started within STALE_AFTER is still going: the user waits. An older one is treated as dead.
        fresh = draft.started_at is not None and timezone.now() - draft.started_at < run.STALE_AFTER
        context = {
            "draft": draft,
            "unfinished": IN_PROGRESS if fresh else UNFINISHED,
            "unfinished_link": not fresh,
        }
        return render(request, "employees/import_preview.html", context)
    closed = _unfinished_redirect(draft)
    if closed is not None:
        return closed
    if not draft.mapping:
        return redirect("employees:import_map", pk=draft.pk)
    allow_salary = access.can_manage_salary(user)
    try:
        preview = plan.build_preview(draft, allow_salary=allow_salary, user=user)
        headings, _ = reader.read_rows(bytes(draft.data), draft.sheet, draft.header_rows)
    except reader.ImportFileError as exc:
        return _upload_page(request, user, UploadForm(), notice=str(exc))
    ignored = [] if allow_salary else _ignored(headings, draft.mapping, StaffImportSettings.get().mapping)

    dept_names = dict(Department.objects.values_list("id", "name"))
    pos_names = dict(Position.objects.values_list("id", "name"))
    rows = []
    for row in preview.rows[:PREVIEW_ROWS]:
        values = row.values
        label, look = STATUS_LOOK[row.status]
        department = dept_names[values["department_id"]] if "department_id" in values else values.get("department", "")
        position = pos_names[values["position_id"]] if "position_id" in values else values.get("position", "")
        rows.append(
            {
                "number": row.number,
                "name": f"{values.get('family_name', '')} {values.get('given_name', '')}".strip(),
                "identity": values.get("register_no") or values.get("passport_no") or "",
                "department": department,
                "position": position,
                "label": label,
                "look": look,
                "note": "; ".join(row.errors) or row.note,
            }
        )
    context = {
        "draft": draft,
        "preview": preview,
        "rows": rows,
        "total_rows": len(preview.rows),
        "confirm_above": CONFIRM_ABOVE,
        "needs_confirm": preview.new > CONFIRM_ABOVE,
        "error": PREVIEW_ERRORS.get(request.GET.get("err", ""), ""),
        "ignored": ignored,
        "allow_salary": allow_salary,
    }
    return render(request, "employees/import_preview.html", context)


def _back_to_preview(draft: StaffImportDraft, code: str) -> HttpResponse:
    url = reverse("employees:import_preview", kwargs={"pk": draft.pk})
    return redirect(f"{url}?err={code}")


@login_required
@require_POST
def import_run(request: HttpRequest, pk: Any) -> HttpResponse:
    user = _user(request)
    draft = _draft(request, pk)
    if draft.state == "imported":
        return redirect("employees:import_result", pk=draft.pk)
    if draft.state == "running":
        return redirect("employees:import_preview", pk=draft.pk)
    allow_salary = access.can_manage_salary(user)
    try:
        preview = plan.build_preview(draft, allow_salary=allow_salary, user=user)
    except reader.ImportFileError:
        return _back_to_preview(draft, "file")
    if preview.new == 0 and preview.errors == 0:
        return _back_to_preview(draft, "none")  # nothing in the file at all
    if preview.new > CONFIRM_ABOVE:
        typed = request.POST.get("confirm_count", "").strip()
        if not typed.isdecimal() or int(typed) != preview.new:
            return _back_to_preview(draft, "count")
    try:
        run.run_import(draft, by=user, allow_salary=allow_salary)
    except run.DraftBusy:
        return _back_to_preview(draft, "busy")  # another import is running
    except run.DraftNotAvailable:
        return _back_to_preview(draft, "claimed")  # only the claim step means "already imported"
    return redirect("employees:import_result", pk=draft.pk)


@login_required
@require_GET
def import_result(request: HttpRequest, pk: Any) -> HttpResponse:
    draft = _draft(request, pk)
    if draft.state == "uploaded":
        return redirect("employees:import_map", pk=draft.pk)
    if draft.state == "running":
        return redirect("employees:import_preview", pk=draft.pk)
    return render(request, "employees/import_result.html", {"draft": draft})


@login_required
@require_GET
def import_rejected(request: HttpRequest, pk: Any) -> HttpResponse:
    draft = _draft(request, pk)
    if draft.state != "imported" or not draft.rejected_file:
        raise Http404
    response = HttpResponse(bytes(draft.rejected_file), content_type=XLSX)
    # An ASCII name for old clients, and the Mongolian name for the rest (RFC 5987).
    disposition = f"attachment; filename=\"rejected-rows.xlsx\"; filename*=UTF-8''{quote(REJECTED_NAME)}"
    response["Content-Disposition"] = disposition
    record_export(request, "staff_import_rejected_download", "Алдаатай мөрүүд", rows=draft.rejected_count)
    return response


@login_required
@require_GET
def import_template(request: HttpRequest) -> HttpResponse:
    user = _manager(request)
    response = HttpResponse(template.template_bytes(include_salary=access.can_manage_salary(user)), content_type=XLSX)
    response["Content-Disposition"] = f'attachment; filename="{TEMPLATE_NAME}"'
    return response
