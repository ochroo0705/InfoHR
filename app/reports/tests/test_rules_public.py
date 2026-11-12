"""The public rule check: ops_for and check_value wrap the private helpers without changing them."""

from reports.rules import OPS, check_value, ops_for


def test_check_value_number_gte_true():
    assert check_value("gte", "5", "number") is True


def test_check_value_number_gte_unreadable_is_false():
    assert check_value("gte", "много", "number") is False


def test_check_value_date_next_days_true():
    assert check_value("next_days", "30", "date") is True


def test_check_value_date_next_days_negative_is_false():
    assert check_value("next_days", "-3", "date") is False


def test_check_value_op_not_allowed_for_kind_is_false():
    assert check_value("next_days", "30", "number") is False


def test_check_value_empty_takes_no_value():
    assert check_value("empty", "", "text") is True


def test_check_value_number_between_true():
    assert check_value("between", "3..9", "number") is True


def test_check_value_unknown_kind_is_false():
    assert check_value("eq", "x", "bogus") is False


def test_ops_for_unknown_kind_is_empty_tuple():
    assert ops_for("bogus") == ()


def test_ops_for_known_kind_matches_ops_table():
    assert ops_for("number") == OPS["number"]
    assert ops_for("date") == OPS["date"]
    assert ops_for("text") == OPS["text"]
