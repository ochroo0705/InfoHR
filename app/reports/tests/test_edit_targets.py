"""The edit target of a table cell (reports.services.edit_targets) against the link the Django template draws.

The template _rows.html draws one data-edit link per cell from a long condition. edit_target() must answer the same
editor for every combination of rights, so the tests render the template for each cell and compare the link with the
target: the route, the employee, the field, the list kind and key, and the job record.
"""

import re
from html import unescape
from itertools import product
from urllib.parse import parse_qs, urlsplit

import pytest
from django.template.loader import render_to_string
from django.urls import reverse

from reports.cell_edit import SALARY_EDITABLE
from reports.services.edit_targets import EditFlags, EditTarget, edit_target, marks_of
from reports.table import Cell

ALL = EditFlags(cells=True, plain=True, salary=True, correct=True, correct_salary=True, rows=True)
NONE = EditFlags(cells=False, plain=False, salary=False, correct=False, correct_salary=False, rows=False)
ROUTE_URLS = {"cell": "reports:cell_edit", "row": "reports:row_cell", "correct": "reports:correct"}


def _cell(**kw: object) -> Cell:
    base: dict[str, object] = {"value": "Бат", "person": 7, "edit_person": 7}
    base.update(kw)
    return Cell(**base)  # type: ignore[arg-type]


def _flags(**kw: bool) -> EditFlags:
    return EditFlags(**{**{f: False for f in ("cells", "plain", "salary", "correct", "correct_salary", "rows")}, **kw})


def _template_flags(flags: EditFlags) -> dict[str, object]:
    return {
        "can_edit_rows": flags.rows,
        "can_correct_cells": flags.correct,
        "can_correct_salary": flags.correct_salary,
        "can_edit_cells": flags.cells,
        "plain_cells": flags.plain,
        "salary_cells": flags.salary,
        "salary_fields": SALARY_EDITABLE,
    }


def _drawn(cell: Cell, flags: EditFlags) -> tuple[object, ...] | None:
    """What the template draws for this cell: (route, person, field, kind, key, record), or None for no link."""
    html = render_to_string(
        "reports/_rows.html",
        {"rows": [[cell]], "selectable": False, **_template_flags(flags)},
    )
    found = re.search(r'data-edit="([^"]*)"', html)
    if found is None:
        return None
    parts = urlsplit(unescape(found.group(1)))
    q = {k: v[0] for k, v in parse_qs(parts.query).items()}
    if parts.path == reverse("reports:cell_edit"):
        return ("cell", int(q["person"]), q["field"], "", 0, 0)
    if parts.path == reverse("reports:row_cell"):
        return ("row", int(q["person"]), q["field"], q["kind"], int(q["key"]), 0)
    assert parts.path == reverse("reports:correct"), parts.path
    return ("correct", int(q["person"]), q["key"], "", 0, int(q.get("record", 0)))


def _target(target: EditTarget) -> tuple[object, ...]:
    return (target.route, target.person, target.field, target.kind, target.key, target.record)


CELLS = [
    _cell(row_kind="child", row_key=5, row_field="name"),  # 1: a list row cell
    _cell(correct="department", record=9),  # 2: a job cell with its record
    _cell(correct="salary", value=500),  # 3: a salary cell with a value
    _cell(edit="family_name"),  # 4: a plain employee field
    _cell(edit="bank"),  # 5: a salary field
    _cell(row_kind="child", row_key=5, row_field="name", correct="department", record=9, edit="family_name"),
    _cell(correct="position", record=3, edit="bank"),  # 7: a job cell without flags falls to its field
    _cell(correct="salary", value=None, edit="bank"),  # 8: a salary cell with no value, a salary field
]
# Cells of a row with no employee. build_table blanks their fields (Cell.edit, Cell.row_kind) so no real table has
# them; the template does not read edit_person, so the parity check leaves them out and the guard is tested alone.
NO_EMPLOYEE = [
    _cell(edit="family_name", edit_person=0),
    _cell(row_kind="child", row_key=5, row_field="name", edit_person=0),
]


@pytest.mark.parametrize("index", range(len(CELLS)))
@pytest.mark.parametrize(
    "flags",
    [ALL, NONE, *[_flags(**{f: True}) for f in ("cells", "plain", "salary", "correct", "correct_salary", "rows")]],
    ids=lambda f: "".join(c for c, on in zip("cpsCSr", astuple(f), strict=True) if on) or "none",
)
def test_target_matches_the_template_link(index: int, flags: EditFlags) -> None:
    cell = CELLS[index]
    target = edit_target(cell, flags)
    drawn = _drawn(cell, flags)
    assert (None if target is None else _target(target)) == drawn
    if drawn is not None:
        assert drawn[1] == cell.edit_person


def test_every_flag_combination_matches_the_template() -> None:
    names = ("cells", "plain", "salary", "correct", "correct_salary", "rows")
    for values in product((False, True), repeat=len(names)):
        flags = EditFlags(**dict(zip(names, values, strict=True)))
        for cell in CELLS:
            target = edit_target(cell, flags)
            assert (None if target is None else _target(target)) == _drawn(cell, flags), (cell, values)


def astuple(flags: EditFlags) -> tuple[bool, ...]:
    return (flags.cells, flags.plain, flags.salary, flags.correct, flags.correct_salary, flags.rows)


def test_row_edit_wins_over_a_correction_and_a_field() -> None:
    target = edit_target(CELLS[5], ALL)
    assert target == EditTarget(route="row", person=7, field="name", kind="child", key=5)


def test_correction_target_carries_the_record_and_the_salary_flag() -> None:
    assert edit_target(CELLS[1], _flags(correct=True)) == EditTarget(
        route="correct", person=7, field="department", record=9
    )
    assert edit_target(CELLS[2], _flags(correct_salary=True)) == EditTarget(
        route="correct", person=7, field="salary", salary=True
    )


def test_plain_and_salary_fields() -> None:
    assert edit_target(CELLS[3], _flags(cells=True, plain=True)) == EditTarget(
        route="cell", person=7, field="family_name"
    )
    assert edit_target(CELLS[4], _flags(salary=True, cells=True)) == EditTarget(
        route="cell", person=7, field="bank", salary=True
    )


@pytest.mark.parametrize("cell", NO_EMPLOYEE)
def test_no_employee_no_target(cell: Cell) -> None:
    assert edit_target(cell, ALL) is None


@pytest.mark.parametrize(
    ("cell", "flags"),
    [
        (_cell(edit="family_name"), _flags(cells=True, salary=True)),  # plain field, no plain right
        (_cell(edit="family_name"), _flags(plain=True)),  # plain field, the cell editors are off
        (_cell(edit="bank"), _flags(cells=True, plain=True)),  # salary field, no salary right
        (_cell(correct="salary", value=None), _flags(correct_salary=True)),  # salary correction with no value
        (_cell(correct="department"), _flags(correct=True)),  # a job correction with no record
        (_cell(correct="department", record=9), _flags(cells=True, plain=True)),  # correction right off
        (_cell(row_kind="child", row_key=5, row_field="name"), _flags(correct=True, cells=True, plain=True)),
        (_cell(), ALL),  # a read-only cell
    ],
)
def test_no_target_when_no_right_or_no_employee(cell: Cell, flags: EditFlags) -> None:
    assert edit_target(cell, flags) is None
    assert _drawn(cell, flags) is None


def test_marks_of_names_each_kind_once_in_legend_order() -> None:
    targets = [
        edit_target(CELLS[0], ALL),  # row
        edit_target(CELLS[3], ALL),  # plain
        edit_target(CELLS[4], ALL),  # salary
        edit_target(CELLS[1], ALL),  # correct
        None,
        edit_target(CELLS[3], ALL),  # plain again
    ]
    assert marks_of(targets) == ["plain", "salary", "correct", "row"]
    assert marks_of([None, None]) == []
