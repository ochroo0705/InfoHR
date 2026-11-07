"""Runs a staff Excel import: creates a person for every row the preview marks as new, and keeps the rows that were
refused in a workbook the user can correct and load again. Each person is written in its own transaction, so one
refused row never undoes the others."""

import io
import logging
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, cast

from accounts.audit import Category, record_safe
from accounts.models import User
from django.db import DataError, IntegrityError, transaction
from django.utils import timezone
from macs.models import Bank, Department, InsuredCategory, Position
from openpyxl import Workbook
from openpyxl.cell import Cell as XlCell
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Font
from openpyxl.worksheet.worksheet import Worksheet

from employees import named_lock
from employees.models import StaffImportDraft
from employees.named_lock import Lock, LockBusy
from employees.services import history, macs_writes, records
from employees.services.personal_writes import PersonalConflict
from employees.staff_import.plan import Preview, build_preview
from employees.staff_import.reader import read_rows
from employees.staff_import.rows import ParsedRow

logger = logging.getLogger(__name__)

REJECTED_SHEET = "Алдаатай мөр"
ERROR_HEADING = "Алдаа"
REFUSED = "Хадгалж чадсангүй"
DATE_FORMAT = "yyyy-mm-dd"
BOLD = Font(bold=True)
# A row whose write is refused: the database or service error is logged, and the user sees REFUSED only.
# OrderError is not listed: hire raises it only with with_order=True, which this import never uses. ValueError stays
# as the net for a malformed value reaching a write; without it one bad cell would abort the whole run.
WRITE_ERRORS = (IntegrityError, DataError, history.HistoryError, PersonalConflict, ValueError)
PERSON_KEYS = (
    "family_name",
    "given_name",
    "register_no",
    "passport_no",
    "birth_date",
    "gender",
    "work_phone",
    "private_phone",
    "email",
)
PLACE_KEYS = ("branch_id", "citizenship_id", "work_conditions")
SALARY_TEXT_KEYS = ("account_no", "social_insurance_no", "health_insurance_no", "taxpayer_no")


def _key(text: str) -> str:
    """Lower case with whitespace collapsed: the same name in two spellings gives one key."""
    return " ".join(text.lower().split())


def _create_lists(preview: Preview) -> tuple[dict[str, Department], dict[str, Position]]:
    """Creates each department and position that does not exist yet, once. Keys are the normalised names."""
    departments = {_key(name): macs_writes.save_department(name) for name in preview.new_departments}
    positions = {_key(name): macs_writes.save_position(name) for name in preview.new_positions}
    return departments, positions


def _department(values: dict[str, Any], created: dict[str, Department]) -> Department:
    if "department_id" in values:
        return Department.objects.get(pk=values["department_id"])
    return created[_key(values["department"])]


def _position(values: dict[str, Any], created: dict[str, Position]) -> Position:
    if "position_id" in values:
        return Position.objects.get(pk=values["position_id"])
    return created[_key(values["position"])]


def _salary_data(values: dict[str, Any]) -> dict[str, Any]:
    """The salary and insurance columns of a row, as update_salary_insurance takes them."""
    data: dict[str, Any] = {key: values[key] for key in SALARY_TEXT_KEYS if key in values}
    if "bank_id" in values:
        data["bank"] = Bank.objects.get(pk=values["bank_id"])
    if "insured_category_id" in values:
        data["insured_category"] = InsuredCategory.objects.get(pk=values["insured_category_id"])
    return data


def _hire_row(
    values: dict[str, Any],
    departments: dict[str, Department],
    positions: dict[str, Position],
    *,
    allow_salary: bool,
    by: User,
) -> None:
    start = values["start"]
    columns: dict[str, Any] = {key: values[key] for key in PERSON_KEYS if key in values}
    columns.update({key: values[key] for key in PLACE_KEYS if key in values})
    columns["first_hire_date"] = start
    job: dict[str, Any] = {
        "position": _position(values, positions),
        "department": _department(values, departments),
        "employee_type": "full_time",
        "status": "active",
        "contract_type": "open_ended",
    }
    salary = values.get("base_salary") if allow_salary else None
    employee = history.hire(
        columns, {"setup_required": False}, start=start, job=job, salary=salary, by=by, with_order=False
    )
    if allow_salary:
        data = _salary_data(values)
        if data:
            records.update_salary_insurance(employee, data, by)


def _write(ws: Worksheet, row: int, column: int, value: object, bold: bool = False) -> None:
    """Writes one value keeping its type. Text is always stored as text, so a value starting with "=" never becomes
    a formula; control characters that old text may hold are removed."""
    cell = cast(XlCell, ws.cell(row=row, column=column))  # a sheet written here has no merged cells
    if bold:
        cell.font = BOLD
    if value is None:
        return
    if isinstance(value, date):
        cell.value = value
        cell.number_format = DATE_FORMAT
    elif isinstance(value, (int, float, Decimal)):
        cell.value = value
    else:
        cell.value = ILLEGAL_CHARACTERS_RE.sub("", str(value))
        cell.data_type = "s"


def _rejected_workbook(headings: list[str], rows: list[ParsedRow]) -> bytes:
    """One sheet: the original headings and a last «Алдаа» column, then the original cells of each refused row."""
    width = max([len(headings), *(len(row.cells) for row in rows)])
    wb = Workbook()
    ws = cast(Worksheet, wb.active)  # a new workbook always has its first sheet
    ws.title = REJECTED_SHEET
    for column in range(1, width + 1):
        heading = headings[column - 1] if column <= len(headings) else None
        _write(ws, 1, column, heading, bold=True)
    _write(ws, 1, width + 1, ERROR_HEADING, bold=True)
    for offset, row in enumerate(rows, start=2):
        for column, value in enumerate(row.cells, start=1):
            _write(ws, offset, column, value)
        _write(ws, offset, width + 1, "; ".join(row.errors))
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


# PostgreSQL advisory key of the import claim lock. _claim takes it through named_lock.take(Lock.STAFF_IMPORT),
# which uses this key on PostgreSQL.
RUN_LOCK_KEY = 7302
# A run that started longer ago than this is treated as dead (the process was killed): it no longer blocks a new run.
STALE_AFTER = timedelta(minutes=30)


class DraftNotAvailable(ValueError):
    """The draft is not in "uploaded" state at the claim: it is running or already imported. Raised only by the
    claim step, so a caller can tell it apart from any other ValueError the run raises."""


class DraftBusy(DraftNotAvailable):
    """Another import is running (it started within STALE_AFTER). Raised only by the claim step."""


def run_import(draft: StaffImportDraft, *, by: User, allow_salary: bool) -> StaffImportDraft:
    """Imports every new row of the draft and stores the counts and the rejected rows on the draft. The file bytes
    are removed at the end. The draft is claimed first ("uploaded" -> "running"), so a second submit cannot import
    the same file again while the first run is going. A run that fails sets the draft back to "uploaded".
    The branch limit of `by` is applied again here, when the rows are planned, so a stale draft cannot create a
    person outside the importer's branches."""
    _claim(draft)
    try:
        draft.refresh_from_db()
        imported = _import(draft, by=by, allow_salary=allow_salary)
    except BaseException:
        # Only a run that did not finish gives the claim back; a finished draft is "imported" and stays so.
        StaffImportDraft.objects.filter(pk=draft.pk, state="running").update(state="uploaded")
        raise
    record_safe(
        Category.IMPORT,
        "staff_import",
        actor=by,
        message=f"{imported.created_count} шинэ, {imported.rejected_count} татгалзсан",
    )
    return imported


def _claim(draft: StaffImportDraft) -> None:
    """Marks the draft "running" if no other import is running. The check and the update share one transaction
    under the STAFF_IMPORT named lock, so two runs cannot both pass the check (a double click, or a re-upload of the
    same file)."""
    now = timezone.now()
    with transaction.atomic():
        try:
            named_lock.take(Lock.STAFF_IMPORT)
        except LockBusy as exc:
            raise DraftBusy("Өөр импорт явагдаж байна.") from exc
        busy = (
            StaffImportDraft.objects.filter(state="running", started_at__gte=now - STALE_AFTER)
            .exclude(pk=draft.pk)
            .exists()
        )
        if busy:
            raise DraftBusy("Өөр импорт явагдаж байна.")
        claimed = StaffImportDraft.objects.filter(pk=draft.pk, state="uploaded").update(state="running", started_at=now)
        if claimed == 0:
            raise DraftNotAvailable("Энэ файлыг аль хэдийн импортолж байна эсвэл импортолсон байна.")


def _import(draft: StaffImportDraft, *, by: User, allow_salary: bool) -> StaffImportDraft:
    preview = build_preview(draft, allow_salary=allow_salary, user=by)
    headings, _ = read_rows(bytes(draft.data), draft.sheet, draft.header_rows)
    departments, positions = _create_lists(preview)

    created = 0
    for row in preview.rows:
        if row.status != "new":
            continue
        try:
            with transaction.atomic():
                _hire_row(row.values, departments, positions, allow_salary=allow_salary, by=by)
        except WRITE_ERRORS as exc:
            logger.exception("staff import row %s refused: %s", row.number, exc)
            row.status = "error"
            row.errors = [REFUSED]
        else:
            created += 1

    rejected = [row for row in preview.rows if row.status == "error"]
    draft.state = "imported"
    draft.created_count = created
    draft.duplicate_count = preview.duplicates
    draft.rejected_count = len(rejected)
    draft.rejected_file = _rejected_workbook(headings, rejected) if rejected else None
    draft.finished_at = timezone.now()
    draft.data = b""
    draft.save()
    return draft
