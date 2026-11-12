"""The catalogue: the views a question may use, with their columns in plain words.

Plain Python only. No Django, no HR imports, no database connection.
Names are stored upper-case and compared case-insensitively.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class Column:
    name: str
    description: str
    synonyms: tuple[str, ...] = ()
    description_mn: str = ""
    label_mn: str = ""  # a short Mongolian name for a table header; "" = show the column name. Not sent to the model.


@dataclass(frozen=True)
class View:
    name: str
    description: str
    columns: tuple[Column, ...]
    description_mn: str = ""
    rules: tuple[str, ...] = ()  # plain-words business rules, for example what counts as working now
    reviewed_by: str = ""  # empty = draft; only the domain owner signs (see the descriptions command)
    reviewed_on: str = ""


def _key(name: str) -> str:
    return name.strip().upper()


@dataclass(frozen=True)
class Catalogue:
    views: tuple[View, ...]

    def view_names(self) -> frozenset[str]:
        return frozenset(_key(view.name) for view in self.views)

    def get(self, name: str) -> View | None:
        wanted = _key(name)
        for view in self.views:
            if _key(view.name) == wanted:
                return view
        return None

    def restrict(self, names: Iterable[str]) -> Catalogue:
        wanted = {_key(name) for name in names}
        return Catalogue(views=tuple(view for view in self.views if _key(view.name) in wanted))
