from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from accounts.models import User
from django.db import models

from reports.filters import Filters


@dataclass(frozen=True)
class Column:
    """One column of a report. A column whose `needs` permission the user lacks is never offered, shown or exported."""

    key: str  # short lowercase word, used in the address (?cols=key)
    label: str  # the header text, Mongolian
    value: Callable[[Any], object]  # the raw value for one row; sorting and grouping use it too
    group: str = ""  # picker group title
    needs: str = ""  # one permission codename, e.g. "macs.view_salary"
    numeric: bool = False  # right-aligned in the table
    money: bool = False  # an amount, shown as 2,500,000₮ (the mnt filter, UI_RULES §2b)
    href: Callable[[Any], str] | None = None  # link target of the cell (e.g. the employee page)


@dataclass(frozen=True)
class Report:
    """A report the catalogue can open. Every report is described once here; the shared page draws it."""

    key: str
    title: str
    filters: tuple[str, ...]  # names of `Filters` fields shown in the filter bar, in order
    columns: tuple[Column, ...]
    default_columns: tuple[str, ...]  # column keys shown when the address names none
    rows: Callable[[User, Filters], list[Any]]  # the rows for these filters, already limited to what the user may see
    needs: tuple[str, ...] = ()  # extra permissions a user must have besides reports.view_reports
    source: type[models.Model] | None = None  # the main table; empty means the grey «бүртгэл алга» marker
    group_options: tuple[str, ...] = ()  # column keys the table may group by
    picks_columns: bool = False  # the user may choose the columns («Багана» button)
    saved_views: bool = False  # the user may save this setup under a name
    note: Callable[[Filters], str] | None = None  # a grey line above the table, e.g. what is historical
    filter_needs: dict[str, str] = field(default_factory=dict)  # filter name -> permission it needs, e.g. gender
    shows_count: bool = True  # the «Нийт: N» line under the table (off when the rows are statistic lines)
