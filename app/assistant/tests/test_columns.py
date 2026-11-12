import json
from collections.abc import Callable

import pytest
from accounts.models import User
from reports import rules
from reports.staff_list import REPORT

from assistant.columns import RuleColumn, offered_columns, plan_extras
from assistant.prompt import columns_block

pytestmark = pytest.mark.django_db


def _by_key(user: User) -> dict[str, RuleColumn]:
    return {c.key: c for c in offered_columns(user)}


def test_hr_has_no_salary_column(role_user: Callable[[str], User]) -> None:
    keys = _by_key(role_user("hr"))
    assert "salary" not in keys
    for key in ("years_worked", "contract_end", "probation_end", "work_phone", "email", "first_hire_date"):
        assert key in keys


def test_accountant_has_salary(role_user: Callable[[str], User]) -> None:
    salary = _by_key(role_user("accountant"))["salary"]
    assert salary.kind == "number"


def test_kinds_and_ops(role_user: Callable[[str], User]) -> None:
    keys = _by_key(role_user("hr"))
    assert keys["years_worked"].kind == "number"
    assert keys["years_worked"].ops == rules.ops_for("number")
    assert keys["contract_end"].kind == "date"


def test_synonyms_cover_the_examples(role_user: Callable[[str], User]) -> None:
    keys = _by_key(role_user("hr"))
    assert "ажилласан жил" in keys["years_worked"].synonyms
    assert "гэрээ дуусах" in keys["contract_end"].synonyms
    assert "утас" in keys["work_phone"].synonyms


def test_offered_columns_follow_allowed_columns(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    offered = [c.key for c in offered_columns(user)]
    assert offered == [c.key for c in REPORT.columns if not c.needs or user.has_perm(c.needs)]


def test_plan_extras_only_for_real_adapters(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")

    class Adapter:
        takes_rules = True

    class Bare:
        pass

    extras = plan_extras(Adapter(), user)
    assert [c.key for c in extras["rule_columns"]] == [c.key for c in offered_columns(user)]
    assert plan_extras(Bare(), user) == {}


def test_columns_block_is_json(role_user: Callable[[str], User]) -> None:
    columns = offered_columns(role_user("hr"))
    heading, body = columns_block(columns).split("\n", 1)
    assert heading
    rows = json.loads(body)
    assert [r["key"] for r in rows] == [c.key for c in columns]
    assert set(rows[0]) == {"key", "label", "kind", "ops", "synonyms"}
