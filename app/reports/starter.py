"""Starter templates («Загвар»): ready-made report setups written as rules. Imports types, filters and rules only, so a
report module can build its templates here without an import cycle."""

from reports.filters import Filters, to_query
from reports.rules import Group, Rule, dump_rules
from reports.types import Template


def view_template(name: str, **setup: object) -> Template:
    """A template written as any report setup: `columns`, `layout`, `lby`, `lby2`, `lval`, `rules`, `sort`… (the
    Filters field names), turned into the address query the report page reads back."""
    return Template(name, to_query(Filters(**setup)))  # type: ignore[arg-type]


def rule_template(name: str, *rules: Rule) -> Template:
    """A template whose rules must all hold (AND), written as the address query the report page reads back."""
    return Template(name, to_query(Filters(rules=dump_rules(Group("and", tuple(rules))))))


def _window_query(name: str, column: str, days: int) -> str:
    return rule_template(name, Rule(column, "next_days", str(days))).query


def soon_template(name: str, column: str) -> Template:
    """A «дөхсөн» template: `column` falls within the next 30 days. `resolved_query` rebuilds it with the company's
    CompanySettings.soon_days window, so the stored query here is only the default."""
    return Template(name, _window_query(name, column, 30), column)


def resolved_query(template: Template) -> str:
    """The address query of a template as it applies now: a «дөхсөн» template uses CompanySettings.soon_days."""
    if not template.soon_column:
        return template.query
    # deferred: this module imports nothing from employees when it loads
    from employees.models import CompanySettings

    return _window_query(template.name, template.soon_column, CompanySettings.get().soon_days)
