"""Starter templates («Загвар»): ready-made report setups written as rules. Imports types, filters and rules only, so a
report module can build its templates here without an import cycle."""

from reports.filters import Filters, to_query
from reports.rules import Group, Rule, dump_rules
from reports.types import Template


def rule_template(name: str, *rules: Rule) -> Template:
    """A template whose rules must all hold (AND), written as the address query the report page reads back."""
    return Template(name, to_query(Filters(rules=dump_rules(Group("and", tuple(rules))))))
