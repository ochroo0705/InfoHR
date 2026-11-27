"""The body of the bulk cell edit (reports.bulk_edit.parse_body): its shape, the types of its values and the 500-cell
cap. Pure checks; the views and the API answer these same texts (test_bulk_edit_views, test_reports_bulk_api)."""

from typing import Any

import pytest

from reports import bulk_edit
from reports.bulk_edit import BulkCell


def _cell(**changes: Any) -> dict[str, Any]:
    cell: dict[str, Any] = {"person": 7, "field": "private_phone", "text": "99110001", "old": ""}
    cell.update(changes)
    return cell


def _body(cells: Any = None, apply: Any = True) -> dict[str, Any]:
    return {"apply": apply, "cells": [_cell()] if cells is None else cells}


def _refused(body: Any) -> str:
    with pytest.raises(ValueError) as caught:
        bulk_edit.parse_body(body)
    return str(caught.value)


@pytest.mark.parametrize("body", [[], "cells", None, 1, True])
def test_a_body_that_is_not_an_object_is_refused(body: Any) -> None:
    assert _refused(body) == bulk_edit.BAD_REQUEST


@pytest.mark.parametrize("apply", [None, "yes", 1, 0])
def test_apply_must_be_a_real_bool(apply: Any) -> None:
    assert _refused(_body(apply=apply)) == bulk_edit.BAD_REQUEST


def test_apply_missing_is_refused() -> None:
    assert _refused({"cells": []}) == bulk_edit.BAD_REQUEST


@pytest.mark.parametrize("cells", ["x", None, {}, 3])
def test_cells_must_be_a_list(cells: Any) -> None:
    assert _refused({"apply": True, "cells": cells}) == bulk_edit.BAD_REQUEST


@pytest.mark.parametrize("cell", ["x", None, 5, ["person"]])
def test_a_cell_that_is_not_an_object_is_refused(cell: Any) -> None:
    assert _refused(_body(cells=[cell])) == bulk_edit.BAD_REQUEST


@pytest.mark.parametrize("person", [True, False, "1", 1.0, None])
def test_person_must_be_a_real_int(person: Any) -> None:
    assert _refused(_body(cells=[_cell(person=person)])) == bulk_edit.BAD_REQUEST


@pytest.mark.parametrize("key", ["field", "text", "old"])
@pytest.mark.parametrize("value", [None, 3, ["x"]])
def test_field_text_and_old_must_be_strings(key: str, value: Any) -> None:
    assert _refused(_body(cells=[_cell(**{key: value})])) == bulk_edit.BAD_REQUEST


def test_a_missing_value_is_refused() -> None:
    cell = _cell()
    del cell["old"]
    assert _refused(_body(cells=[cell])) == bulk_edit.BAD_REQUEST


def test_a_valid_body_gives_the_apply_flag_and_the_cells() -> None:
    apply, cells = bulk_edit.parse_body(
        _body(cells=[_cell(), _cell(person=8, field="email", text="a@b.mn", old="")], apply=False)
    )
    assert apply is False
    assert cells == [
        BulkCell(person=7, field="private_phone", text="99110001", old=""),
        BulkCell(person=8, field="email", text="a@b.mn", old=""),
    ]


def test_500_cells_are_accepted() -> None:
    apply, cells = bulk_edit.parse_body(_body(cells=[_cell()] * bulk_edit.MAX_CELLS))
    assert apply is True
    assert len(cells) == bulk_edit.MAX_CELLS


def test_501_cells_are_refused_with_too_many() -> None:
    assert _refused(_body(cells=[_cell()] * (bulk_edit.MAX_CELLS + 1))) == bulk_edit.TOO_MANY


def test_the_django_texts_are_unchanged() -> None:
    assert bulk_edit.BAD_REQUEST == "Буруу хүсэлт"
    assert bulk_edit.TOO_MANY == "Нэг удаад 500 хүртэл нүд"
