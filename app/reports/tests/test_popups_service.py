"""The request-free pop-up models (services/popups.py): the columns, rules and format pop-ups' current values, the
columns the user may see, and `keep`, the cleaned address minus the part each pop-up owns."""

from dataclasses import replace

import pytest
from accounts.models import User
from django.core.exceptions import PermissionDenied
from django.http import Http404, QueryDict

from reports.services.popups import (
    _rule_kind as rule_kind,
)
from reports.services.popups import (
    check_popup,
    columns_model,
    format_model,
    rules_model,
)
from reports.types import Column, Report

pytestmark = pytest.mark.django_db

KEY = "popups-service-test"
SCORE_RULE = '{"op":"and","items":[{"c":"score","o":"gt","v":"2"}]}'
SCORE_MARK = '[{"c":"score","o":"gt","v":"2","k":"green"}]'


def _report(**changes: object) -> Report:
    """Name and score are shown to HR; pay needs the salary permission (HR lacks it)."""
    report = Report(
        key=KEY,
        title="Тест тайлан",
        filters=("state",),
        columns=(
            Column(key="name", label="Нэр", value=lambda r: r.name, group="Ажилтан"),
            Column(key="score", label="Оноо", value=lambda r: r.score, group="Ажилтан", numeric=True),
            Column(
                key="pay",
                label="Цалин",
                value=lambda r: r.pay,
                group="Цалин",
                needs="macs.view_salary",
                numeric=True,
                money=True,
            ),
        ),
        default_columns=("name", "score"),
        rows=lambda user, filters: [],
        group_options=("name",),
        picks_columns=True,
        shows_count=True,
    )
    return replace(report, **changes)


def _with_offer() -> Report:
    """The base report plus a column filter the user may use: «Үндэс угсаа» through the nationality column."""
    base = _report()
    nationality = Column(key="nationality", label="Үндэс угсаа", value=lambda r: "", group="Ажилтан")
    return replace(base, columns=(*base.columns, nationality), column_filters=("nationality",))


@pytest.mark.parametrize(
    "model",
    [columns_model, rules_model, format_model],
    ids=["columns", "rules", "format"],
)
def test_add_chips_survive_the_round_trip_once_and_offered_only(hr_user: User, model) -> None:
    get = QueryDict("add=nationality&add=nationality&add=citizenship")  # citizenship is not offered by this report
    keep = model(get, hr_user, _with_offer()).keep
    assert keep.count(("add", "nationality")) == 1
    assert ("add", "citizenship") not in keep


def test_columns_model_marks_shown_columns_and_lists_group_choices(hr_user: User) -> None:
    model = columns_model(QueryDict("cols=score&group=name"), hr_user, _report())
    assert [(title, [(p.key, p.checked) for p in picks]) for title, picks in model.groups] == [
        ("Ажилтан", [("name", False), ("score", True)])
    ]  # HR does not see pay, so the «Цалин» group is absent
    assert [c.key for c in model.group_choices] == ["name"]
    assert model.group == "name"
    assert model.group_text == ""  # one key: the select's own option shows it


def test_columns_model_keep_drops_cols_and_group_and_keeps_filters_and_adds(hr_user: User) -> None:
    model = columns_model(QueryDict("state=all&cols=score&group=name"), hr_user, _report())
    assert all(name not in ("cols", "group") for name, _ in model.keep)
    assert ("state", "all") in model.keep


def test_columns_model_group_drops_hidden_column(hr_user: User) -> None:
    # the hidden column is keyed «salary» as in the API test; a single hidden key is dropped, and a visible multi-key
    # group keeps the visible key (the hidden one goes), so the select never echoes a column HR may not see
    base = _report()
    report = replace(
        base,
        columns=tuple(replace(c, key="salary") if c.key == "pay" else c for c in base.columns),
        group_options=("name", "salary"),
    )
    hidden = columns_model(QueryDict("group=salary"), hr_user, report)
    assert hidden.group == ""
    assert hidden.group_text == ""
    assert all(name != "group" for name, _ in hidden.keep)
    mixed = columns_model(QueryDict("group=name,salary"), hr_user, report)
    assert mixed.group == "name"
    assert mixed.group_text == ""  # one visible key left: the select's own option shows it


def test_rules_model_lists_only_allowed_columns(hr_user: User) -> None:
    model = rules_model(QueryDict(""), hr_user, _report())
    assert [(c.key, c.kind) for c in model.columns] == [("name", "text"), ("score", "number")]
    assert "eq" in [op.code for op in model.ops["number"]]


def test_rules_model_keep_drops_rules_only(hr_user: User) -> None:
    get = QueryDict(f"cols=score&totals=score:sum&rules={SCORE_RULE}")
    model = rules_model(get, hr_user, _report())
    assert model.rules != ""
    assert all(name != "rules" for name, _ in model.keep)
    assert ("cols", "score") in model.keep
    assert ("totals", "score:sum") in model.keep


def test_format_model_current_totals_marks_pin_are_restricted_to_allowed_columns(hr_user: User) -> None:
    get = QueryDict(
        "cols=name&cols=pay&totals=pay:sum,score:avg&pin=2"
        '&marks=[{"c":"pay","o":"gt","v":"0","k":"red"},{"c":"score","o":"gt","v":"2","k":"green"}]'
    )
    model = format_model(get, hr_user, _report())
    assert model.totals == [("score", "avg")]  # pay is hidden from HR, so its total is dropped
    assert [(m.c, m.o, m.v, m.k) for m in model.marks] == [("score", "gt", "2", "green")]
    assert model.shown == ["name"]
    assert model.pin == 2


def test_format_model_keep_drops_totals_marks_pin(hr_user: User) -> None:
    get = QueryDict(f"cols=score&totals=score:sum&marks={SCORE_MARK}&pin=2&state=all")
    model = format_model(get, hr_user, _report())
    assert all(name not in ("totals", "marks", "pin") for name, _ in model.keep)
    assert ("cols", "score") in model.keep
    assert ("state", "all") in model.keep


def test_rule_kind_falls_back_to_number_for_money_then_text() -> None:
    assert rule_kind(Column(key="a", label="", value=lambda r: r, kind="date")) == "date"
    assert rule_kind(Column(key="b", label="", value=lambda r: r, money=True)) == "number"
    assert rule_kind(Column(key="c", label="", value=lambda r: r, numeric=True)) == "number"
    assert rule_kind(Column(key="d", label="", value=lambda r: r)) == "text"


def test_check_popup_404_before_403(hr_user: User) -> None:
    nobody = User.objects.create_user("popups-nobody", password="x-long-pass-123")  # noqa: S106
    no_picks = _report(picks_columns=False)
    with pytest.raises(Http404):
        check_popup(nobody, no_picks, needs="picks_columns")  # 404 first, even for a user who may not open it
    with pytest.raises(Http404):
        check_popup(hr_user, None, needs="picks_columns")
    with pytest.raises(PermissionDenied):
        check_popup(nobody, _report(), needs="picks_columns")
    check_popup(hr_user, _report(), needs="picks_columns")  # no exception


def test_keep_never_echoes_hidden_column(hr_user: User) -> None:
    pay_rule = '{"op":"and","items":[{"c":"pay","o":"gt","v":"0"}]}'
    get = QueryDict(
        f'cols=pay&group=pay&rules={pay_rule}&totals=pay:sum&marks=[{{"c":"pay","o":"gt","v":"0","k":"red"}}]&pin=1'
    )
    report = _report()
    columns = columns_model(get, hr_user, report)
    rules = rules_model(get, hr_user, report)
    fmt = format_model(get, hr_user, report)
    for keep in (columns.keep, rules.keep, fmt.keep):
        assert ("cols", "pay") not in keep
        assert ("group", "pay") not in keep
        assert ("totals", "pay:sum") not in keep
        assert all(value != "pay" for _, value in keep)
    assert rules.rules == ""  # the only rule is on pay, which HR may not see
    assert fmt.totals == []
    assert fmt.marks == []
    assert ("pin", "1") not in fmt.keep  # the pin is the format pop-up's own part
    assert fmt.pin == 1  # a valid pin is not tied to a column, so it stays
