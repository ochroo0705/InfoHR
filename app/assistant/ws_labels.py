"""Mongolian names for the columns of a workspace table.

A workspace table is the result of saved SQL, so its column names are database identifiers (FIRST_NAME). The governed
view descriptions carry a short Mongolian label per column (`label_mn` in hr_sql/descriptions/*.toml); this module
finds the label for each result column. Labels are for display only: every address, form value and SQL statement
keeps the column name.

A column gets a label only when it is safe to say what it is:
- its name is a column of a governed view that the saved SQL names (an alias such as CNT has no label);
- the views the SQL names agree on the label (BIRTH_DATE of GOV_EMPLOYEES and of GOV_CHILDREN differ: no label
  when both are in the SQL);
- no other column of the same result would show the same label (two «Төлөв» columns would be indistinguishable).
Otherwise the column name is shown, as before.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Sequence

from sqlcore.catalogue import View

COUNT_LABEL = "Тоо"  # the count column of a grouped table (ws_sql.COUNT_NAME)


def _named(view: View, sql: str) -> bool:
    """True when the SQL text names the view as a whole word, in any case."""
    return re.search(rf"(?<![A-Za-z0-9_$]){re.escape(view.name)}(?![A-Za-z0-9_$])", sql, re.IGNORECASE) is not None


def view_labels(views: Iterable[View], sql: str) -> dict[str, str]:
    """Upper-case column name -> label, from the views the SQL names. A name whose views disagree is left out."""
    found: dict[str, set[str]] = {}
    for view in views:
        if not _named(view, sql):
            continue
        for column in view.columns:
            if column.label_mn:
                found.setdefault(column.name.upper(), set()).add(column.label_mn)
    return {name: next(iter(labels)) for name, labels in found.items() if len(labels) == 1}


def display_names(columns: Sequence[str], labels: dict[str, str]) -> dict[str, str]:
    """Upper-case column name -> what the page shows for it, for these result columns: the label, or the column name
    itself when it has no label or when another column of the result would show the same text."""
    shown = {name.upper(): labels.get(name.upper(), name) for name in columns}
    counts = Counter(shown.values())
    return {upper: (text if counts[text] == 1 else upper) for upper, text in shown.items()}
