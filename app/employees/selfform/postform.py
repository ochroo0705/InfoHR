"""Converts the public form's ordinary fields to the answers shape, and back.

Field names: person-<key>, contact-<key>, edu-<i>-<key>, fam-<i>-<key>, where <i> is the row number (0, 1, 2...).
Rows whose values are all blank are left out. The number of rows read is capped at the list's limit plus one, so
the validator (validate_answers) can refuse an over-long list, and a crafted body cannot make this loop long.
"""

import re
from typing import Any

from django.http import QueryDict

from employees.selfform.answers import (
    CONTACT_FIELDS,
    EDUCATION_FIELDS,
    FAMILY_FIELDS,
    MAX_EDUCATION,
    MAX_FAMILY,
    PERSON_FIELDS,
)

EDU_PREFIX = "edu"  # field-name prefix of the education rows
FAM_PREFIX = "fam"  # field-name prefix of the family rows
_INDEX = re.compile(r"[0-9]{1,6}")  # a row number; longer digit strings are not row numbers


def _rows(post: QueryDict, prefix: str, fields: tuple[str, ...], cap: int) -> list[dict[str, str]]:
    indices: set[int] = set()
    for key in post.keys():
        parts = key.split("-", 2)
        if len(parts) == 3 and parts[0] == prefix and parts[2] in fields and _INDEX.fullmatch(parts[1]):
            indices.add(int(parts[1]))
    rows: list[dict[str, str]] = []
    for index in sorted(indices):
        row = {name: post.get(f"{prefix}-{index}-{name}", "") for name in fields}
        if all(not value.strip() for value in row.values()):
            continue
        rows.append(row)
        if len(rows) > cap:  # one more than the cap is enough for the validator to refuse the list
            break
    return rows


def answers_from_post(post: QueryDict) -> dict[str, Any]:
    """The answers {"person", "education", "family", "contact"} from the posted form fields. Values are strings."""
    return {
        "person": {name: post.get(f"person-{name}", "") for name in PERSON_FIELDS},
        "education": _rows(post, EDU_PREFIX, EDUCATION_FIELDS, MAX_EDUCATION),
        "family": _rows(post, FAM_PREFIX, FAMILY_FIELDS, MAX_FAMILY),
        "contact": {name: post.get(f"contact-{name}", "") for name in CONTACT_FIELDS},
    }


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def initial_from_answers(answers: dict[str, Any]) -> dict[str, str]:
    """The form field values for stored answers, under the same names answers_from_post reads."""
    initial: dict[str, str] = {}
    for name, value in _dict(answers.get("person")).items():
        if name in PERSON_FIELDS:
            initial[f"person-{name}"] = _text(value)
    for name, value in _dict(answers.get("contact")).items():
        if name in CONTACT_FIELDS:
            initial[f"contact-{name}"] = _text(value)
    for prefix, key, fields in ((EDU_PREFIX, "education", EDUCATION_FIELDS), (FAM_PREFIX, "family", FAMILY_FIELDS)):
        rows = answers.get(key)
        for index, row in enumerate(rows if isinstance(rows, list) else []):
            for name in fields:
                initial[f"{prefix}-{index}-{name}"] = _text(_dict(row).get(name))
    return initial
