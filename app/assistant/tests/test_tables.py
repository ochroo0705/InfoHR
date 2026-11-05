from collections.abc import Callable

import pytest
from accounts.models import User
from macs.models import Department

from assistant.plan import Part
from assistant.tables import MAX_BUTTONS, Settled, settle

pytestmark = pytest.mark.django_db

NOT_OFFERED = "Ийм шүүлтүүр байхгүй эсвэл танд нээлттэй биш."


def _part(param: str, value: str) -> Part:
    return Part(param=param, value=value)


def _no_value(value: str) -> str:
    return f"“{value}” гэсэн утга олдсонгүй."


def test_fixed_and_dates_apply(role_user: Callable[[str], User]) -> None:
    user: User = role_user("hr")
    result = settle(user, [_part("emptype", "5"), _part("hired_from", "2020-01-01")])
    assert ("emptype", "5") in result.params
    assert ("hired_from", "2020-01-01") in result.params
    assert result.ask is None
    assert result.rest == ()


@pytest.mark.parametrize("value", ["8", "9"])
def test_unconfirmed_emptype_values_apply(role_user: Callable[[str], User], value: str) -> None:
    user: User = role_user("hr")
    assert settle(user, [_part("emptype", value)]).params == (("emptype", value),)


def test_lookup_one_applies(role_user: Callable[[str], User]) -> None:
    user: User = role_user("hr")
    dept = Department.objects.create(name="Санхүү")
    result = settle(user, [_part("department", "санхүү")])
    assert result.params == (("department", str(dept.pk)),)
    assert result.ask is None


def test_ambiguous_asks_and_defers_rest(role_user: Callable[[str], User]) -> None:
    user: User = role_user("hr")
    Department.objects.create(name="Санхүүгийн хяналт")
    Department.objects.create(name="Санхүүгийн төлөвлөлт")
    later = _part("emptype", "5")
    result = settle(user, [_part("department", "санхүү"), later])
    assert result.ask is not None
    assert result.ask.param == "department"
    assert len(result.ask.candidates) == 2
    assert result.ask.more is False
    assert result.rest == (later,)
    assert result.params == ()


def test_ask_caps_buttons(role_user: Callable[[str], User]) -> None:
    user: User = role_user("hr")
    for i in range(8):
        Department.objects.create(name=f"Санхүүгийн хэсэг {i}")
    result = settle(user, [_part("department", "санхүү")])
    assert result.ask is not None
    assert MAX_BUTTONS == 5
    assert len(result.ask.candidates) == 5
    assert result.ask.more is True


def test_no_match_is_listed(role_user: Callable[[str], User]) -> None:
    user: User = role_user("hr")
    result = settle(user, [_part("department", "маркетинг")])
    assert result.params == ()
    assert result.ask is None
    assert result.not_applied == (_no_value("маркетинг"),)


def test_not_offered_filter_is_not_applied(role_user: Callable[[str], User]) -> None:
    user: User = role_user("auditor")
    result = settle(user, [_part("salary_from", "2000000")])
    assert result.params == ()
    assert result.not_applied == (NOT_OFFERED,)


def test_bad_values(role_user: Callable[[str], User]) -> None:
    # The accountant holds view_salary, so the salary part reaches the number check.
    user: User = role_user("accountant")
    result = settle(
        user,
        [
            _part("hired_from", "2020-13-45"),
            _part("emptype", "99"),
            _part("salary_from", "12abc"),
            _part('x"; DROP TABLE', "1"),
        ],
    )
    assert result.params == ()
    assert result.not_applied == (
        _no_value("2020-13-45"),
        _no_value("99"),
        _no_value("12abc"),
        NOT_OFFERED,
    )


def test_age_bounds(role_user: Callable[[str], User]) -> None:
    user: User = role_user("hr")
    result = settle(
        user,
        [
            _part("age_from", "500"),
            _part("age_to", "-1"),
            _part("age_to", "121"),
            _part("age_from", "30"),
        ],
    )
    assert result.params == (("age_from", "30"),)
    assert result.not_applied == (_no_value("500"), _no_value("-1"), _no_value("121"))


def test_base_is_kept_and_replaced(role_user: Callable[[str], User]) -> None:
    user: User = role_user("hr")
    result = settle(user, [_part("emptype", "1")], base={"emptype": "5"})
    assert result.params == (("emptype", "1"),)


def test_rejected_part_keeps_earlier_value(role_user: Callable[[str], User]) -> None:
    user: User = role_user("hr")
    result = settle(user, [_part("emptype", "99")], base={"emptype": "5"})
    assert result.params == (("emptype", "5"),)
    assert result.not_applied == (_no_value("99"),)


def test_params_follow_registry_order(role_user: Callable[[str], User]) -> None:
    # The base lists gender before emptype; the registry lists emptype first, and so must the result.
    user: User = role_user("hr")
    result = settle(
        user,
        [_part("hired_from", "2020-01-01"), _part("emptype", "1")],
        base={"gender": "M", "emptype": "5"},
    )
    assert result == Settled(
        params=(("emptype", "1"), ("gender", "M"), ("hired_from", "2020-01-01")),
        ask=None,
        rest=(),
        not_applied=(),
    )


def test_base_valid_lookup_id_is_kept(role_user: Callable[[str], User]) -> None:
    user: User = role_user("hr")
    dept = Department.objects.create(name="Санхүү")
    result = settle(user, [], base={"department": str(dept.pk)})
    assert result.params == (("department", str(dept.pk)),)


def test_base_nonexistent_id_is_dropped(role_user: Callable[[str], User]) -> None:
    user: User = role_user("hr")
    result = settle(user, [], base={"department": "999999"})
    assert result.params == ()


def test_base_drops_unknown_and_bad_values(role_user: Callable[[str], User]) -> None:
    user: User = role_user("auditor")
    result = settle(
        user,
        [],
        base={"salary_from": "1000", "emptype": "77", "department": "999999", "bogus": "1", "as_of": "2020-01-01"},
    )
    assert result.params == ()
    assert result.not_applied == ()


def test_unmapped_words_listed(role_user: Callable[[str], User]) -> None:
    user: User = role_user("hr")
    result = settle(user, [], unmapped=["хөлс"])
    assert result.not_applied == ("“хөлс” — ийм шүүлтүүр алга.",)


def test_long_user_text_is_cut_in_lines(role_user: Callable[[str], User]) -> None:
    user: User = role_user("hr")
    long_text = "а" * 500
    result = settle(user, [_part("department", long_text), _part("emptype", long_text)], unmapped=[long_text])
    cut = "а" * 80 + "…"
    assert result.not_applied == (_no_value(cut), _no_value(cut), f"“{cut}” — ийм шүүлтүүр алга.")


def test_reversed_range_passes_unchanged(role_user: Callable[[str], User]) -> None:
    user: User = role_user("hr")
    result = settle(user, [_part("hired_from", "2022-01-01"), _part("hired_to", "2020-01-01")])
    assert ("hired_from", "2022-01-01") in result.params
    assert ("hired_to", "2020-01-01") in result.params
