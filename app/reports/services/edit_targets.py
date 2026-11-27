"""The inline editor each table cell opens, and for whom (decision D-080, step 5f).

edit_target() is the one rule that _rows.html draws as a data-edit link: a list row's field first, then a correction (a
job cell with its record, or a salary cell with a value), then the employee field itself (a plain field for a manager,
a salary field for the salary right). The React page gets the same answer per cell as `edit` and sends it back: it
never names a field or a route of its own. The save routes check the right again, so a target is never a permission.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from reports.cell_edit import SALARY_EDITABLE
from reports.table import Cell

EDIT_MARKS = ("plain", "salary", "correct", "row")  # the legend's order: the kinds of editor a table can show


@dataclass(frozen=True)
class EditTarget:
    route: Literal["cell", "row", "correct"]  # the editor: an employee field, a list row's field, or a correction
    person: int  # the employee the editor saves for (the cell's edit_person)
    field: str  # the cell field, the row field, or the correction key (corrections.KEYS)
    kind: str = ""  # the list kind of a row target, "" otherwise
    key: int = 0  # the row's id in that list of a row target, 0 otherwise
    record: int = 0  # the job record a correction edits, 0 when there is none
    salary: bool = False  # the salary right opens it (a salary field, or the salary correction)


@dataclass(frozen=True)
class EditFlags:
    """The rights the page reads, computed once per page (reports.services.table_page)."""

    cells: bool  # the inline editors of the table cells (table layout, and either right)
    plain: bool  # the employee-management right: plain fields
    salary: bool  # the salary right: salary and insurance fields
    correct: bool  # job corrections are on (the setting, the table layout and the management right)
    correct_salary: bool  # the salary correction is on (the setting, the table layout and both rights)
    rows: bool  # the list row editors (table layout and the management right)


def edit_target(cell: Cell, flags: EditFlags) -> EditTarget | None:
    """The editor this cell opens for these rights, or None for a plain cell (no employee, or no right)."""
    person = cell.edit_person
    if not person:
        return None
    if flags.rows and cell.row_kind and cell.row_key and cell.row_field:
        return EditTarget(route="row", person=person, field=cell.row_field, kind=cell.row_kind, key=cell.row_key)
    salary_correction = cell.correct == "salary"
    if (flags.correct and cell.correct and cell.record) or (
        flags.correct_salary and salary_correction and cell.value is not None
    ):
        return EditTarget(
            route="correct", person=person, field=cell.correct, record=cell.record, salary=salary_correction
        )
    if flags.cells and cell.edit:
        if cell.edit in SALARY_EDITABLE:
            return EditTarget(route="cell", person=person, field=cell.edit, salary=True) if flags.salary else None
        return EditTarget(route="cell", person=person, field=cell.edit) if flags.plain else None
    return None


def mark_of(target: EditTarget) -> str:
    """The legend kind of one target: a row, a correction, a salary field or a plain field."""
    if target.route == "row":
        return "row"
    if target.route == "correct":
        return "correct"
    return "salary" if target.salary else "plain"


def marks_of(targets: Iterable[EditTarget | None]) -> list[str]:
    """The legend kinds the targets include, in EDIT_MARKS order; each once."""
    present = {mark_of(t) for t in targets if t is not None}
    return [mark for mark in EDIT_MARKS if mark in present]
